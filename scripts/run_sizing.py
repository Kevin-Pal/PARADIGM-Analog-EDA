from paradigm.turbo import Turbo1_Plus
import numpy as np
import torch
import math
import matplotlib
import matplotlib.pyplot as plt
import re, json, os
import subprocess, time

# Interface
# Use CSMC018
technique_path = './circuits/design_space.json'

# Read [ckt_name];[GBW];[PM];[DC_gain];[Idd] from user input
input_str = input('\033[31mPlease input the performance goal: [ckt_name];[GBW];[PM];[DC_gain];[Idd]\n')

try:
    ckt_name, GBW, PM, DC_gain, Idd = input_str.split(';')
    GBW = float(GBW)
    PM = float(PM)
    DC_gain = float(DC_gain)
    Idd = float(Idd)
except:
    print('Input format error!')
    exit()

print(f"Optimization target is set as: {ckt_name}, GBW={GBW}Hz, PM={PM}°, DC_gain={DC_gain}dB, Idd={Idd}A\033[0m")

# 0820Version，support multiple scs/mdl pairs, obtain different metrics from different simulation files, and merge them into one result file—only the testbench sections may differ between pairs; the subckt sections must remain identical so variables are inserted correctly
# Use only name as the key for subsequent simulations; do not retain source filenames
scs_mdl_paths = [
    {'scs': f'./circuits/{ckt_name}_da.scs', 'mdl': f'./circuits/{ckt_name}_da.mdl', 'name': 'da'},
    {'scs': f'./circuits/{ckt_name}_tran.scs', 'mdl': f'./circuits/{ckt_name}_tran.mdl', 'name': 'tran'}
    ]
run_path = './runs'
result_path = './result'

# | Amp   | C_load | GBW   | PM   | Gain  | Idd   |
# | ----- | ------ | ----- | ---- | ----- | ----- |
# | SMC   | 10pF   | 10MHz | 60°  | 70dB  | 150ua |
# | NMCNR | 50pF   | 5MHz  | 60°  | 120dB | 600ua |
# This must match the variable names used to save simulation results in the mdl files
performance_goal = {}
performance_goal['GBW_VOUT'] = GBW
performance_goal['PM_VOUT'] = PM
performance_goal['DC_gain'] = DC_gain
performance_goal['Idd'] = Idd
performance_goal['Pdiss'] = performance_goal['Idd'] * 1.8

optimization_with_initial_flag = False  # Whether to optimize using netlist initial values


def str_to_num(origin_value:str):

    str_=origin_value
    mul = 1
    if "T" in str_:
        mul = 1e12
    if "G" in str_:
        mul = 1e9
    if "M" in str_:
        mul = 1e6
    if "k" in str_ or "K" in str_:
        mul = 1e3
    if "m" in str_:
        mul = 1e-3
    if "u" in str_:
        mul = 1e-6
    if "n" in str_:
        mul = 1e-9
    if "p" in str_:
        mul = 1e-12
    if "f" in str_:
        mul = 1e-15
    num_str = "".join(filter(lambda ch: ch in '0123456789.', str_))
    if  str_.startswith('-'):
        return -float(num_str) * mul
    else:
        return float(num_str) * mul

def variables_generation(netlist_file_path:str,
                        instance_local:list[str] = None):
    """
    The first argument is the path to the simulated circuit .scs file
    The second argument contains the names of circuit elements to optimize; use None for global optimization(useless in this module)
    """

    full_variables = []
    # instance_local = [item.strip().replace('"','').replace("'",'') for item in instance_local]
    # for item in instance_local:
    #     print(item)
    with open (netlist_file_path, mode='r') as f:
        netlist_raw = f.read()
    
    netlist_raw = netlist_raw.split("\n")
    netlist_ = []
    flag = 0

    for line in netlist_raw:
        if  line.startswith("subckt"):
            flag = 1
        if  line.startswith("ends"):
            flag = 0
            # 0522 update: also read content outside subckt
            # 0820 update: in the paper experiments, content outside subckt is the testbench and should not be read
        if  flag == 1:
            netlist_.append(line)
    # This effectively reads only the content between subckt and ends, with comments removed
    # print(f"the netlist is {netlist_}")
    
    for line in netlist_:
        # Skip comments and lines starting with subckt or ends
        if  line.startswith("//") or line.startswith("subckt") or line.startswith("ends"):
            continue
        
        line = line.replace("(","").replace(")","")
        # Strip extra leading and trailing whitespace from line
        line = line.strip()

        if  'not' in line:#bias transistor or bias resistor should not be changed
            continue
        
        instance_name = line.split(' ')[0]
        
        # Insert using the same comment-like method

        if  instance_local == None or instance_name in instance_local: 
            # Check if the ABC mode is local mode——local optimization?
            current_instances = []
            for  variable in full_variables:
                for instance in list(variable.keys())[0]:
                    current_instances.append(instance) #list the instances that have been added

            if instance_name in current_instances: # If the instance has been added
                continue
            
            if  '`' in line:
                # If the instance has the same parameters with other instances
                # Use a comment-like marker to denote //// Input transistor, 1st stage ``NM0``
                same_instance_flag = re.search(r"``(.*?)``",line,re.DOTALL)
                # print(same_instance_flag)
                if same_instance_flag:
                    same_instance = same_instance_flag.group(1)
                    instances = (instance_name,same_instance)
                else:
                    instances = (instance_name,)
            else:
                instances = (instance_name,)
            
            # print(full_variables)
            # an example of full_variables
            # [{('start_up_NM1',): ['w', 1e-06]}, {('start_up_NM1',): ['l', 1e-06]}, {('start_up_C0',): ['c', 1e-11]}]
            
            exist_flag = 0
            # to deal with the situation that there are more than two instances sharing the same parameters
            # full_variables stores the organized device parameters; each parameter is a dictionary whose key is a device name (possibly multiple devices) and whose value is the device parameter
            # instances is a tuple of device names; multiple names indicate that the devices share the same parameters
            
            full_variables_copy = full_variables.copy()
            # If the loop modifies the object being iterated over, copy it first and iterate over the copy
            
            for variable in full_variables_copy:
                # Compare each device in the new variable with the devices in existing entries for overlap
                instances_exsited = list(list(variable.keys())[0])
                
                # print(instances_exsited)
                # print(full_variables)
                
                # If the current entry (instances) already exists in full_variables, add all devices in instances to the corresponding full_variables entry
                for instance_sub in instances:
                    if instance_sub in instances_exsited:
                        # add the new instance to the existed instance
                        # The two entries should be merged
                        # Merge the non-overlapping device names from instances with instances_exsited
                        new_instances = instances_exsited.copy()
                        for instance in instances:
                            if instance not in instances_exsited:
                                new_instances.append(instance)
                        
                        # print(f"the instances_exsited is {instances_exsited}")
                        new_variable_key = tuple(new_instances)
                        # print(f"the new_variable_key is {new_variable_key}")
                        # full_variables is an array whose elements are dictionaries; variable is a complete dictionary rather than a key-value pair (although it contains only one element)
                        # print(variable.values())
                        full_variables.append({new_variable_key:list(variable.values())[0]})
                        full_variables.remove(variable)
                        exist_flag = 1
                        break
                
            if exist_flag == 1:
                continue
                    
                
            # print(instances)
            items = line.split(' ')
            # print(f"the items is {items}")
            # items contains the individual fields on one line

            params = []
            for item in items:
                if '=' in item:
                    
                    param_name = item.split('=')[0]
                    param_value = item.split('=')[1]
                    
                    if  param_name == 'm':
                        #do not load the information of m
                        continue
                    elif param_name == 'w' :
                        #multiply the w with m
                        # Ignore the value of m by setting it to 1, then multiply w by the old m and fold it into the total width
                        try:
                            param_value = float(param_value)
                        except:
                            param_value = str_to_num(param_value)
                            
                        for item_w in items:
                            #load the information of m
                            if '=' in item_w:
                                
                                param_name_w = item_w.split('=')[0]
                                param_value_w = item_w.split('=')[1]
                                # Find the value of m
                                if  param_name_w == 'm':
                                    try:
                                        param_value_w = float(param_value_w)
                                    except:
                                        try:
                                            param_value_w = str_to_num(param_value_w)
                                        except:
                                            param_value_w = exec(param_value_w)
                                            # Handle m primarily; it may sometimes be an expression
                                    param_value *= param_value_w
                        params.append([param_name,param_value])
                    
                    else:
                        # This covers l, resistors, and capacitors
                        try:
                            param_value = float(param_value)
                        except:
                            param_value = str_to_num(param_value)
                        # print(param_name,param_value)
                        params.append([param_name,param_value])
            for param in params:
                full_variables.append({instances:param})
    # print(full_variables)
            
    return full_variables

def width_2_fw_m(w:float,
                fw_min:float):
    # Split an overly wide single gate into multiple gate widths and fingers
    # print(f"the w is {w} and the fw_min is {fw_min}")
    if w < fw_min:
        # print(f'the result is {w}, 1')
        return w , 1
    else:
        fingers = 1
        fw = w/fingers
        while fw >= fw_min:
            fingers += 1
            fw = w/fingers
            
        # fingers -= 1
        # print(f'the result is {w/fingers}, {fingers}')
        return float(format(w/fingers,'.4g')), fingers

def write_vector2netlist(params:list[list[str],str],
                    variables:list[float],
                    fw_min:float,
                    file:str):
    """
    params: equal to CircuitParams.params
    
    variables: the vector of values for the parameters  (equal to CircuitParams.vector)
    
    fw_min: the minimum value of the finger width (equal to CircuitParams.wsub)
    
    file: the path of the netlist(.scs) file
    """
    param_dict={}
    for i,param in enumerate(params):
        inst_names = param[0]
        param_name = param[1]
        value = float(format(variables[i],'.4g'))
        param_name = param_name.lower()
        if param_name == 'w':
            fw,finger = width_2_fw_m(value,fw_min)
            for inst_name in inst_names:
                if  inst_name not in param_dict.keys():
                    param_dict[inst_name]={'w':fw}
                    param_dict[inst_name]['m']=finger
                else:
                    param_dict[inst_name]['w']=fw
                    param_dict[inst_name]['m']=finger
        else:
            for inst_name in inst_names:
                if  inst_name not in param_dict.keys():
                    param_dict[inst_name]={param_name:value}
                else:
                    param_dict[inst_name][param_name]=value
    # print(param_dict)
    with open(file, mode='r') as f:
        lines=f.readlines()
        line_modified=[]
        for line in lines:
            # print(f'the origin line is {line}')
            origin_line = line
            line_with_no_comment = line.split('//')[0]
            comment = line.split('//')[-1]
            # print(f'the comment is {comment}')
            inst_name=line_with_no_comment.split(' ')[0]
            # print(line_with_no_comment)
            if  inst_name in param_dict.keys():
                inst_info, inst_params=line_with_no_comment.split(')',1)
                inst_params=inst_params.split(' ')
                m_flag = False
                for i,inst_param in enumerate(inst_params):
                    if  '=' in inst_param:
                        param_name=inst_param.split('=')[0]

                        if  param_name == 'm':
                            m_flag = True
                        if  param_name in param_dict[inst_name].keys():
                            inst_param=param_name+'='+str(param_dict[inst_name][param_name])
                    inst_params[i]=inst_param
                
                if m_flag == False:
                    if 'm' in param_dict[inst_name].keys():
                        inst_params.append('m='+str(param_dict[inst_name]['m']))
                    else:
                        inst_params.append('m=1')
                
                line=f'{inst_info})'
                for inst_param in inst_params:
                    if  inst_param !='':
                        line+=' '+inst_param.strip()
                if  '//' in origin_line:
                    line+=' ////' + comment
                else:
                    line+='\n'
                # line+=' ////' + comment
            line_modified.append(line)
            # print(f'the modified line is {line}')
    with open(file, mode='w') as f:
        f.writelines(line_modified)
    
    return True

def find_matching_scs_mdl(path)->list:
    """
    Find same-named scs and mdl files under the specified path (treated as pairs), and return a list of their matching names without extensions
    """
    # Check whether the directory exists
    if not os.path.exists(path):
        print(f"The specified path {path} does not exist.")
        return {}
    
    scs_box = []
    mdl_box = []
    pair_box = []
    
    # Traverse the specified directory
    for filename in os.listdir(path):
        # Get the full path of the file
        full_path = os.path.join(path, filename)
        # Check whether it is a file
        if os.path.isfile(full_path):
            # Split the filename into its base name and extension
            base_name, extension = os.path.splitext(filename)
            if extension == '.scs':
                scs_box.append(base_name)
            elif extension == '.mdl':
                mdl_box.append(base_name)
            else:
                pass
        else:
            pass
    
    # Match scs and mdl files
    for scs in scs_box:
        if scs in mdl_box:
            pair_box.append(scs)
    
    return pair_box

def read_performance(run_path:str, 
                    print_flag : bool = 0)->dict[str:float]:
    """
    Simulate all same-named scs and mdl files (scs_mdl_pair) under the specified path, write the results to a single result file, read it, and return the performance metrics
    """
    result = {}
    # Run the simulation
    pair_box = find_matching_scs_mdl(run_path)
    
    if len(pair_box) == 0:
        print(f"No matching scs and mdl files found in the specified path {run_path}")
        return {}
    
    if print_flag:
        print(f"Matching scs and mdl files found: {pair_box}")
        print(f"Running spectre simulation")
    
    for i in range(len(pair_box)):
        if i == 0:
            os.system(f'cd {run_path} && spectremdl -batch {pair_box[i]}.mdl -design {pair_box[i]}.scs +mt=3 >/dev/null && cat {pair_box[i]}.measure > result')
        else:
            os.system(f'cd {run_path} && spectremdl -batch {pair_box[i]}.mdl -design {pair_box[i]}.scs +mt=3 >/dev/null && cat {pair_box[i]}.measure >> result')    # Append to the result file
    
    # Read the result file
    with open(f"{run_path}/result", mode='r') as f:
        lines = f.readlines()
        for line in lines:
            if  '=' in line:
                line = line.split('=')
                result[line[0].strip()] = float(line[1].strip())
    return result

def read_multiple_performances(run_paths:list[str], 
                    print_flag : bool = 0)->list[dict[str:float]]:
    """
    Run simulations in parallel
    
    For each element of run_paths, simulate all same-named scs and mdl files (scs_mdl_pair) in parallel, write the results to a single result file, read it, and return the performance metrics
    """
    
    count = 0
    
    # prepare the commands to be executed in parallel
    commands = []
    for run_path in run_paths:
        pair_box = find_matching_scs_mdl(run_path)
        if len(pair_box) == 0:
            print(f"No matching scs and mdl files found in the specified path {run_path}")
            return {}
        if print_flag:
            print(f"Matching scs and mdl files found: {pair_box}")
        for pair in pair_box:
            commands.append(f'cd {run_path} && spectremdl -batch {pair}.mdl -design {pair}.scs +mt=3 >/dev/null')
            count += 1
            
    if print_flag:
        print(f"Running {count} spectre simulations in parallel")
        
    # must enable shell=True to run commands in the form of a string
    # subprocess.Popen("pwd", shell=True)
    # subprocess.Popen("cd ./runs && ls", shell=True)
    
    # run the commands in parallel
    processes = [subprocess.Popen(command, shell=True) for command in commands]
    
    # wait for all processes to finish and then read the results
    for process in processes:
        process.wait()
        
    # read the results
    results = []
    for run_path in run_paths:
        pair_box = find_matching_scs_mdl(run_path)
        for i in range(len(pair_box)):
            if i == 0:
                os.system(f'cd {run_path} && cat {pair_box[i]}.measure > result')
            else:
                os.system(f'cd {run_path} && cat {pair_box[i]}.measure >> result')
        
        with open(f"{run_path}/result", mode='r') as f:
            lines = f.readlines()
            result = {}
            for line in lines:
                if  '=' in line:
                    # print(line)
                    line = line.split('=')
                    result[line[0].strip()] = float(line[1].strip())
        results.append(result)
            
    return results

def fitness_function_essay(
    present_performance:dict[str:float],
    performance_goal:dict[str:float],
    print_flag:bool = 0)->float:
    """
    Compute fitness using only GBW_VOUT, PM_VOUT, DC_gain, and `Pdiss` (dictionary keys must match the mdl variable names)
    
    Implement the Modified fitness function from Algorithm 1 in the paper (optimize only `Pdiss`; the other targets only need to be met)
    
    Higher is better
    """
    loss = 0
    for Ind in ['GBW_VOUT','PM_VOUT','DC_gain']:        
        Ind_ = present_performance[Ind]
        Ind_tgt = performance_goal[Ind]
        if print_flag:
            print(f"{Ind} : {Ind_tgt} vs {Ind_}")
        if  Ind_ < Ind_tgt:
            loss += max(1e-6, ((Ind_tgt - Ind_)/Ind_)**2)
        else:
            loss += 0
    
    for Ind in ['Pdiss']:
        Ind_ = present_performance[Ind]
        Ind_tgt = performance_goal[Ind]
        if print_flag:
            print(f"{Ind} : {Ind_tgt} vs {Ind_}")
        if Ind_ < Ind_tgt:
            loss += 0
        else:
            loss += max(1e-6, ((Ind_tgt - Ind_)/Ind_tgt)**2)
         
    fitness = 0   
    if loss == 0:
        fitness = 1e6
        for Ind in ['Pdiss']:
            Ind_ = present_performance[Ind]
            Ind_tgt = performance_goal[Ind]
            fitness *= Ind_tgt/Ind_
    else:
        fitness = 1/loss
        
    return fitness

def fitness_function_ABC(
    result:dict[str:float],
    op_tgt:dict[str:float],
    print_flag:bool = 0)->float:
    """
    Compute fitness using only GBW_VOUT, PM_VOUT, DC_gain, and `Pdiss` (dictionary keys must match the mdl variable names)
    
    The metrics SR_N, SR_P, GM_VOUT, and UGB are also considered, but are not optimized and require transient simulation
    
    Higher is better
    """
    try:
        # print(result)
        dc_gain = float(result["DC_gain"])
        GBW_VOUT = float(result["GBW_VOUT"])
        PM_VOUT = float(result["PM_VOUT"])
        # PM must also be reduced modulo 180
        # PM_VOUT = PM_VOUT % 180
        # # Apply the modulo only to SMC
        # if ckt_name == 'SMC':
        #     PM_VOUT = PM_VOUT % 180
        Pdiss = float(result["Pdiss"])
        SR_P = float(result["SR_P"])
        SR_N = float(result["SR_N"])
        GM = float(result["GM_VOUT"])
        UGB = float(result["UGB"])
        try:    # This parameter is unavailable for the SMC circuit
            gm2 = float(result["gm2"])
            gm3 = float(result["gm3"])
        except:
            gm2 = None
            gm3 = None
        
        dc_gain_require = op_tgt["DC_gain"]
        PM_VOUT_require = op_tgt["PM_VOUT"]
    except:
        print("\033[31mError: The result dictionary does not contain the required keys.\033[0m")
        return None
    
    fitness = 0
    for item in result.keys():
        if item == "DC_gain":
            fitness += (
                0
                if dc_gain > dc_gain_require
                else ((dc_gain_require - dc_gain) / dc_gain) ** 2
            )
            if print_flag:
                print(f"DC_gain : {dc_gain_require} vs {dc_gain}")
        elif item == "PM_VOUT":
            if 90 > PM_VOUT > PM_VOUT_require:
                fitness += 0
            elif PM_VOUT < PM_VOUT_require:
                fitness += ((PM_VOUT_require - PM_VOUT) / PM_VOUT) ** 2
            else:
                fitness += 1    # Handle NaN values
            if print_flag:
                print(f"PM_VOUT : {PM_VOUT_require} vs {PM_VOUT}")
        elif item == "GBW_VOUT":
            if np.isnan(GBW_VOUT):
                fitness += 1
            else:
                fitness += (
                    0
                    if GBW_VOUT > op_tgt[item]
                    else ((op_tgt[item] - GBW_VOUT) / GBW_VOUT) ** 2
                )
            if print_flag:
                print(f"GBW_VOUT : {op_tgt[item]} vs {GBW_VOUT}")
        elif item == "Pdiss":
            fitness += (
                0
                if Pdiss < op_tgt[item]
                else ((Pdiss - op_tgt[item]) / (op_tgt[item])) ** 2
            )
            multiply = op_tgt[item] / Pdiss
            if print_flag:
                print(f"Pdiss : {op_tgt[item]} vs {Pdiss}")
    if np.isnan(SR_N):
        fitness += 1
        if print_flag:
            print(f"SR_N is NaN")
    if np.isnan(SR_P):
        fitness += 1
        if print_flag:
            print(f"SR_P is NaN")
    if np.isnan(GM) or float(GM) > 0:
        fitness += 1
        if print_flag:
            print(f"GM is abnormal")
    if gm2 is not None and gm3 is not None:
        if gm2 > gm3:
            fitness += 1
            if print_flag:
                print(f"gm2 is larger than gm3")
    
    UGB_GBW_max = max(UGB,GBW_VOUT)
    UGB_GBW_min = min(UGB,GBW_VOUT)
    if  UGB_GBW_min < UGB_GBW_max * 0.9:
        fitness += 1
        # # Skip this comparison for SMC for now
        # if ckt_name == 'SMC':
        #     fitness -= 1
        
        if print_flag:
            print(f"UGB is much too different from GBW")
    # if np.isnan(GM) or float(GM) >0:
    #         fitness += 1
    # print(result)
    # print(fitness)
    # FOM_S = GBW_VOUT / Pdiss * 10**3
    # FOM_L = (SR_N + SR_P) / 2 / Pdiss * 10**9
    # print(FOM_S)
    # print(FOM_L)
    # print(FOM_S*10e-12)
    # print(FOM_L*10e-12)
    # print(multiply)
    if fitness == 0:
        fitness = multiply * 1e4
    else:
        fitness = min(1 / fitness, 1e4)

    return fitness
    
class CircuitParams:
    '''
    At initialization, read the netlist and process parameters to obtain the following information:
    ----------------
    
    1.variables : a list of device names, device types, and device parameters; parameters come from the original netlist
        e.g. [{('start_up_NM1',): ['w', 9.1e-07]}, {('start_up_NM1',): ['l', 9.6e-07]}, {('start_up_C0',): ['c', 9.216e-12]}, ...]
        includes netlist parameter values for initializing the optimization algorithm
        
    2.params : a list of device names and device types without device parameters
        e.g. [[('start_up_NM1',), 'w'], [('start_up_NM1',), 'l'], [('start_up_C0',), 'c'], ...]
        has no netlist parameter values; used with vector as optimization input and for writing parameters to the netlist and simulator
        
    3.vector : the optimization input vector; a list of device parameter values that depends on whether netlist initial values are used
        e.g. [9.1e-07, 9.6e-07, 9.216e-12, ...]
        contains no device names or types and is used as optimization input
        
    4.lb, ub ,step : the search range for each parameter (upper bound, lower bound, and step), with the same structure and length as vector
        e.g. [9e-07, 9.6e-07, 9e-12, ...]
        contains no device names or types and is used as optimization input
    
    '''
    
    def __init__(self, scs_path, technique_path, initial_flag:bool = False):
        self.get_technique_params(technique_path)
        self.variables = variables_generation(scs_path)
        self.params = [[list(value.keys())[0],list(value.values())[0][0]] for value in self.variables]
        self.vector = self.get_initial_value(initial_flag)
        self.lb, self.ub, self.step = self.get_lb_ub_step(initial_flag)
        
    def get_technique_params(self, technique_path):
        with open(technique_path, 'r') as f:
            abc_parameter = json.load(f)
        self.lmin = abc_parameter["lmin"]
        self.lmax = abc_parameter["lmax"]
        self.wmin = abc_parameter["wmin"]
        self.wmax = abc_parameter["wmax"]
        self.VDD = abc_parameter["VDD"]
        self.step_sub = abc_parameter["step_sub"]    # transistor gate-width and gate-length precision (step size)
        self.wsub = abc_parameter["wsub"]    # maximum gate width for a single finger
        self.avoid = abc_parameter["avoid"]    # some process libraries report errors for unusual device sizes; 180 nm does not have this issue
    
    def get_initial_value(self, initial_flag:bool):
        '''
        Return the initial value of vector, depending on whether netlist initial values are used for optimization
        '''
        if initial_flag:  # (1) Optimize using netlist initial values
            initial_value = []
            for value in self.variables:
                initial_value.append(list(value.values())[0][1])
        else:   # (2) Optimize without initial values
            initial_value = []
            for value in self.variables:
                param_cur = list(value.values())[0][0]
                if  param_cur == 'w':
                    initial_value.append((self.wmin+self.wmax)/2)
                elif param_cur == 'l':
                    initial_value.append((self.lmin+self.lmax)/2)
                elif param_cur == 'c':
                    initial_value.append(1.5e-12)
                elif param_cur == 'r':
                    initial_value.append(1000)
                elif param_cur == 'm':
                    initial_value.append(1)
        return initial_value
        
    def get_lb_ub_step(self, initial_flag:bool):
        '''
        Return per-dimension lower and upper bounds for vector (defining the parameter search space) and the step size, depending on whether netlist initial values are used
        '''
        if initial_flag:  # (1) Optimize using netlist initial values
            infimum = []
            supremum = []
            step = []
            for i,value in enumerate(self.variables):
                param_cur = list(value.values())[0][0]
                if  param_cur == 'w':
                    min_width = max(self.wmin,list(value.values())[0][1]*0.5)
                    infimum.append((min_width-min_width%self.step_sub)+self.step_sub)
                    supremum.append(min(list(value.values())[0][1]*1.3,self.wmax))
                    step.append(self.step_sub)
                elif param_cur == 'l':
                    min_len = max(self.lmin,list(value.values())[0][1]*0.5)
                    infimum.append((min_len-min_len%self.step_sub)+self.step_sub)
                    supremum.append(min(self.lmax,list(value.values())[0][1]*1.3))
                    step.append(self.step_sub)   # the step sizes for w and l depend on the precision supported by the process
                elif param_cur == 'm':
                    infimum.append(list(value.values())[0][1])
                    supremum.append(list(value.values())[0][1])
                    step.append(1)
                else:
                    infimum.append(list(value.values())[0][1]*0.8)
                    supremum.append(list(value.values())[0][1]*1.2)
                    step.append(list(value.values())[0][1]/1000)
        
        else:   # (2) Optimize without initial values
             infimum = [] # Set the optimization search space
             supremum = []
             for value in self.variables:
                param_cur = list(value.values())[0][0]
                if  param_cur == 'w':
                    infimum.append(self.wmin)            
                    supremum.append(self.wmax)
                elif param_cur == 'l':
                    infimum.append(self.lmin)
                    supremum.append(self.lmax)
                elif param_cur == 'c':
                    infimum.append(0.5e-12)
                    supremum.append(3e-12)
                elif param_cur == 'r':
                    infimum.append(1)
                    supremum.append(20000)
                elif param_cur == 'm':
                    infimum.append(1)
                    supremum.append(1)
             step = [float(format(value/100,'.1g')) for value in self.vector]
             
        return infimum, supremum, step
            
# fitness function, lower is better
class FitnessFunction:
    
    def __init__(self, scs_mdl_paths:list[dict[str,str]], run_path, ckt_name, performance_goal, params, wsub, print_flag:bool = 1):
        self.scs_mdl_paths = scs_mdl_paths  # list of dict, key is 'scs', 'mdl' and 'name', value is the path of the file or the mdl name
        self.run_path = run_path
        self.ckt_name = ckt_name
        self.performance_goal = performance_goal    # dict, key is the name of performance, value is the dict of value, type
        self.params = params    # corresponding to CircuitParams.params
        self.wsub = wsub    # corresponding to CircuitParams.wsub
        self.print_flag = print_flag
        
        # Copy mdl_file and scs_file to the run_path/ckt_name directory
        try:
            os.makedirs(os.path.join(run_path, ckt_name))
        except FileExistsError:
            pass
        
        # Clear all old scs and mdl files before copying
        try:
            os.system(f'rm {os.path.join(run_path, ckt_name)}/*.scs')
            os.system(f'rm {os.path.join(run_path, ckt_name)}/*.mdl')
        except:
            pass
        
        for scs_mdl_path in scs_mdl_paths:
            scs_path = scs_mdl_path['scs']
            mdl_path = scs_mdl_path['mdl']
            type_name = scs_mdl_path['name']
            
            os.system(f'cp {scs_path} {f"{os.path.join(run_path, ckt_name)}/TurBO_{type_name}.scs"}')
            os.system(f'cp {mdl_path} {f"{os.path.join(run_path, ckt_name)}/TurBO_{type_name}.mdl"}')
        
    def __call__(self, x:list[float]) -> float:
        """
        Lower is better，fitness below 1 means that all targets have been met
        """
        # write the vector to the netlist file
        mdl_run_path = os.path.join(self.run_path, self.ckt_name)
        for scs_mdl_path in self.scs_mdl_paths:
            write_vector2netlist(self.params, x, self.wsub, f"{mdl_run_path}/TurBO_{scs_mdl_path['name']}.scs")
        
        # run the simulation and get the performance
        present_performance = read_performance(mdl_run_path)
        
        # calculate the fitness
        result = fitness_function_ABC(present_performance, self.performance_goal, self.print_flag)
        
        # TuRBOM fitness is minimized, so its reciprocal is taken; a value below 1 means that all targets have been met
        # result = FITNESS_THRE/result  # reciprocal method, but subsequent convergence is too slow
        result = -result    # simple and aggressive, but may not be supported (it is supported)
        
        return result
         
# fitness function, lower is better
class FitnessFunction_Prallel:
    
    def __init__(self, scs_mdl_paths, run_path, ckt_name, performance_goal, params, wsub, print_flag:bool = 1):
        self.scs_mdl_paths = scs_mdl_paths  # list of dict, key is 'scs', 'mdl' and 'name', value is the path of the file or the mdl name
        self.run_path = run_path
        self.ckt_name = ckt_name
        self.performance_goal = performance_goal    # dict, key is the name of performance, value is the dict of value, type and relation
        self.params = params    # corresponding to CircuitParams.params
        self.wsub = wsub    # corresponding to CircuitParams.wsub
        self.print_flag = print_flag
        
        
        try:
            os.makedirs(os.path.join(run_path, ckt_name))
        except FileExistsError:
            # Clear all subdirectories under the original directory
            try:
                os.system(f'rm -rf {os.path.join(run_path, ckt_name)}/TurBO_*')
            except:
                pass
        
        
    def __call__(self, x:list[list[float]]) -> float:
        """
        Lower is better，fitness below 1 means that all targets have been met
        """
        # get the parallel number
        n = len(x)
        
        mdl_run_paths = []
        
        # copy scs and mdl files to different directories and write each vector to the netlist file
        for i in range(n):
            mdl_run_path = os.path.join(self.run_path, self.ckt_name) + f"/TurBO_{i}"
            try:
                os.makedirs(mdl_run_path)
            except FileExistsError:
                pass
            mdl_run_paths.append(mdl_run_path)
            
            
            for scs_mdl_path in self.scs_mdl_paths:
                scs_path = scs_mdl_path['scs']
                mdl_path = scs_mdl_path['mdl']
                type_name = scs_mdl_path['name']
                os.system(f'cp {scs_path} {f"{mdl_run_path}/TurBO_{type_name}.scs"}')
                os.system(f'cp {mdl_path} {f"{mdl_run_path}/TurBO_{type_name}.mdl"}')

                write_vector2netlist(self.params, x[i], self.wsub, f"{mdl_run_path}/TurBO_{type_name}.scs")
        
        # run the simulations and get the performances in parallel
        present_performances = read_multiple_performances(mdl_run_paths)
        
        results = []
        
        
        for present_performance in present_performances:
            # calculate the fitness
            result = fitness_function_ABC(present_performance, self.performance_goal, self.print_flag)
            
            # TuRBOM fitness is minimized, so its reciprocal is taken; a value below 1 means that all targets have been met
            # result = FITNESS_THRE/result  # reciprocal method, but subsequent convergence is too slow
            # print(result)
            result = -result    # simple and aggressive, but may not be supported (it is supported)
            
            results.append([result])
        
        return results
        
        
circuit = CircuitParams(scs_mdl_paths[0]["scs"], technique_path, optimization_with_initial_flag)

dim = len(circuit.variables)

f_parallel = FitnessFunction_Prallel(scs_mdl_paths, run_path, ckt_name, performance_goal, circuit.params, circuit.wsub, 0)

Chat_Turbo1_Plus = Turbo1_Plus(
    f=f_parallel,
    lb=np.array(circuit.lb),
    ub=np.array(circuit.ub),
    n_init=2*dim,  # number of initial points for each trust region, fix the value to 10 or 2*dim
    max_evals=99999,
    max_iters=100,
    batch_size=10,
    f_threshold=-1e4,
    x_init=None, # or circuit.vector
    device='cpu',
)

start_time = time.time()
Chat_Turbo1_Plus.optimize()
end_time = time.time()
print(f"\033[31mTime cost: {end_time-start_time} s \033[0m")

X = Chat_Turbo1_Plus.X
fX = Chat_Turbo1_Plus.fX
index_best = np.argmin(fX)
f_best, x_best = fX[index_best], X[index_best]

print("Best value found:\n\tf(x) = %.4g\nObserved at:\n\tx = %s" % (f_best, np.array2string(x_best, formatter={'float_kind':lambda x: "%.3g" % x})))

# Save results

try:
    os.makedirs(result_path)
except FileExistsError:
    pass

# Clear the result directory
try:
    os.makedirs(f'{result_path}/{ckt_name}')
except FileExistsError:
    os.system(f'rm -rf {result_path}/{ckt_name}/*')

for scs_mdl_path in scs_mdl_paths:
    scs_path = scs_mdl_path['scs']
    mdl_path = scs_mdl_path['mdl']
    type_name = scs_mdl_path['name']
    os.system(f'cp {scs_path} {result_path}/{ckt_name}/TuBRO_{type_name}_result.scs')
    os.system(f'cp {mdl_path} {result_path}/{ckt_name}/TuBRO_{type_name}_result.mdl')
    # Insert the optimum and write it to the .scs file
    write_vector2netlist(circuit.params, x_best, circuit.wsub, f"{result_path}/{ckt_name}/TuBRO_{type_name}_result.scs")
    # Run the simulation
    os.system(f'cd {result_path}/{ckt_name} && spectremdl -batch TuBRO_{type_name}_result.mdl -design TuBRO_{type_name}_result.scs +mt=3 >/dev/null && cat *.measure > result')
    # Delete extraneous files under the result directory (except *.mdl, *.scs, and result)
    os.system(f'cd {result_path}/{ckt_name} && rm -rf *.log *.raw *.mt0 *.mt1 *.mt2 *.mt3 *.mt4')

# # Clear run_path/ckt_name after completion to avoid consuming disk space
# try:
#     os.system(f'rm -rf {run_path}/{ckt_name}/*')
# except:
#     pass