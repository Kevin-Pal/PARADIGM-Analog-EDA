from paradigm.turbo import Turbo1_Plus
import numpy as np
import torch
import math
import matplotlib
import matplotlib.pyplot as plt
import re, json, os
import subprocess, time

# Command-line interface.
# Use the CSMC 0.18 µm design-space bounds.
technique_path = './circuits/design_space.json'

# Read [ckt_name];[GBW];[PM];[DC_gain];[Idd] from standard input.
input_str = input('\033[31mPlease input the performance goal: [ckt_name];[GBW];[PM];[DC_gain];[Idd];[initial_vector]\n')

try:
    ckt_name, GBW, PM, DC_gain, Idd, initial_vector = input_str.split(';')
    GBW = float(GBW)
    PM = float(PM)
    DC_gain = float(DC_gain)
    Idd = float(Idd)
    # Parse the bracketed, space-separated initial vector.
    initial_vector = initial_vector.strip('[]').split(' ')
    initial_vector = [float(item) for item in initial_vector]
    # Shape: (1, dim).
    initial_vector = np.array(initial_vector).reshape(1, -1)
except:
    print('Input format error!')
    exit()

print(f"Optimization target is set as: {ckt_name}, GBW={GBW}Hz, PM={PM}°, DC_gain={DC_gain}dB, Idd={Idd}A\033[0m")

# Update 0820: support multiple SCS/MDL pairs and merge their metrics; testbench sections may differ, but subcircuit sections must match so parameters are inserted consistently.
# Use only the analysis name as the downstream key; do not retain source filenames.
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
# These keys must match the result names written by the MDL files.
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
    """Parse optimizable variables from a Spectre netlist.

    Args:
        netlist_file_path: Path to the circuit SCS file.
        instance_local: Device names to optimize, or None for global optimization."""

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
            # Update 0522: optionally read content outside the subcircuit.
            # Update 0820: for the paper experiments, ignore testbench content outside the subcircuit.
        if  flag == 1:
            netlist_.append(line)
    # Read only the uncommented content between subckt and ends.
    # print(f"the netlist is {netlist_}")
    
    for line in netlist_:
        # Skip comments and subckt/ends declarations.
        if  line.startswith("//") or line.startswith("subckt") or line.startswith("ends"):
            continue
        
        line = line.replace("(","").replace(")","")
        # Strip leading and trailing whitespace.
        line = line.strip()

        if  'not' in line:# Bias transistors and bias resistors must remain unchanged.
            continue
        
        instance_name = line.split(' ')[0]
        
        # Preserve the netlist's inline-comment convention when inserting parameters.

        if  instance_local == None or instance_name in instance_local: 
            # Check whether ABC mode requests local optimization.
            current_instances = []
            for  variable in full_variables:
                for instance in list(variable.keys())[0]:
                    current_instances.append(instance) # Track the instances already added.

            if instance_name in current_instances: # If the instance is already present:
                continue
            
            if  '`' in line:
                # If the instance shares parameters with other instances:
                # Parse markers such as “//// Input transistor, 1st stage `NM0`”.
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
            # Example full_variables value:
            # [{('start_up_NM1',): ['w', 1e-06]}, {('start_up_NM1',): ['l', 1e-06]}, {('start_up_C0',): ['c', 1e-11]}]
            
            exist_flag = 0
            # Handle cases where more than two instances share a parameter.
            # full_variables stores organized device parameters; each dictionary maps one or more device names to a parameter.
            # instances is a tuple of device names; multiple names share the same parameter.
            
            full_variables_copy = full_variables.copy()
            # If the loop modifies the object being iterated over, copy it first and iterate over the copy
            
            for variable in full_variables_copy:
                # Compare each device in the new variable with the devices in existing entries for overlap
                instances_exsited = list(list(variable.keys())[0])
                
                # print(instances_exsited)
                # print(full_variables)
                
                # If instances overlaps an existing full_variables entry, merge all device names into that entry.
                for instance_sub in instances:
                    if instance_sub in instances_exsited:
                        # Add the new instance to the existing group.
                        # The two entries should be merged
                        # Merge non-overlapping names from instances into instances_exsited.
                        new_instances = instances_exsited.copy()
                        for instance in instances:
                            if instance not in instances_exsited:
                                new_instances.append(instance)
                        
                        # print(f"the instances_exsited is {instances_exsited}")
                        new_variable_key = tuple(new_instances)
                        # print(f"the new_variable_key is {new_variable_key}")
                        # full_variables is a list of one-entry dictionaries; variable refers to the whole dictionary.
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
            # items contains the fields parsed from one line.

            params = []
            for item in items:
                if '=' in item:
                    
                    param_name = item.split('=')[0]
                    param_value = item.split('=')[1]
                    
                    if  param_name == 'm':
                        # Do not load multiplier m as a separate parameter.
                        continue
                    elif param_name == 'w' :
                        # Fold multiplier m into width w.
                        # Set m to 1 and fold its original value into the total width w.
                        try:
                            param_value = float(param_value)
                        except:
                            param_value = str_to_num(param_value)
                            
                        for item_w in items:
                            # Load multiplier m as a separate parameter.
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
                                            # Handle m first because it may be an expression.
                                    param_value *= param_value_w
                        params.append([param_name,param_value])
                    
                    else:
                        # This branch covers l, resistors, and capacitors.
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
    # Split an oversized gate into multiple fingers.
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
    """Write a parameter vector into a Spectre netlist.

    Args:
        params: Parameter descriptors from CircuitParams.params.
        variables: Values ordered like CircuitParams.vector.
        fw_min: Minimum finger width from CircuitParams.wsub.
        file: Destination SCS netlist path."""
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
    """Return the stems of same-named SCS/MDL pairs in a directory."""
    # Verify that the directory exists.
    if not os.path.exists(path):
        print(f"The specified path {path} does not exist.")
        return {}
    
    scs_box = []
    mdl_box = []
    pair_box = []
    
    # Traverse the directory.
    for filename in os.listdir(path):
        # Resolve the full file path.
        full_path = os.path.join(path, filename)
        # Process files only.
        if os.path.isfile(full_path):
            # Split the filename into its stem and extension.
            base_name, extension = os.path.splitext(filename)
            if extension == '.scs':
                scs_box.append(base_name)
            elif extension == '.mdl':
                mdl_box.append(base_name)
            else:
                pass
        else:
            pass
    
    # Match same-stem SCS and MDL files.
    for scs in scs_box:
        if scs in mdl_box:
            pair_box.append(scs)
    
    return pair_box

def read_performance(run_path:str, 
                    print_flag : bool = 0)->dict[str:float]:
    """Run each SCS/MDL pair in a directory and merge its measured metrics."""
    result = {}
    # Run the simulation.
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
            os.system(f'cd {run_path} && spectremdl -batch {pair_box[i]}.mdl -design {pair_box[i]}.scs +mt=3 >/dev/null && cat {pair_box[i]}.measure >> result')    # Append to the result file.
    
    # Read the result file.
    with open(f"{run_path}/result", mode='r') as f:
        lines = f.readlines()
        for line in lines:
            if  '=' in line:
                line = line.split('=')
                result[line[0].strip()] = float(line[1].strip())
    return result

def read_multiple_performances(run_paths:list[str], 
                    print_flag : bool = 0)->list[dict[str:float]]:
    """Run read_performance for multiple directories in parallel."""
    
    count = 0
    
    # Prepare commands for parallel execution.
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
        
    # shell=True is required because each command is stored as a shell string.
    # subprocess.Popen("pwd", shell=True)
    # subprocess.Popen("cd ./runs && ls", shell=True)
    
    # Run the commands in parallel.
    processes = [subprocess.Popen(command, shell=True) for command in commands]
    
    # Wait for all processes to finish before reading results.
    for process in processes:
        process.wait()
        
    # Read the results.
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
    """Compute the modified Algorithm 1 fitness from GBW_VOUT, PM_VOUT, DC_gain, and Pdiss.

    Only Pdiss is optimized; the remaining metrics are constraints. Higher values are better."""
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
    """Compute fitness from GBW_VOUT, PM_VOUT, DC_gain, and Pdiss.

    SR_N, SR_P, GM_VOUT, and UGB are validity checks rather than optimization objectives. Higher values are better."""
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
        try:    # This metric is unavailable for the SMC circuit.
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
                fitness += 1    # Handle NaN values.
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
    """Parse a netlist and process bounds into optimization parameters.

    Attributes:
        variables: Device/parameter descriptors with netlist initial values.
        params: Device/parameter descriptors without values.
        vector: Ordered optimization values.
        lb, ub, step: Per-parameter bounds and quantization steps."""
    
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
        self.step_sub = abc_parameter["step_sub"]    # Transistor width/length quantization step.
        self.wsub = abc_parameter["wsub"]    # Maximum gate width per finger.
        self.avoid = abc_parameter["avoid"]    # Device sizes rejected by a process library; none are needed for this 180 nm process.
    
    def get_initial_value(self, initial_flag:bool):
        """Return the optimization vector with or without netlist initial values."""
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
        """Return per-parameter lower bounds, upper bounds, and quantization steps."""
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
                    step.append(self.step_sub)   # The w/l steps follow the process quantization.
                elif param_cur == 'm':
                    infimum.append(list(value.values())[0][1])
                    supremum.append(list(value.values())[0][1])
                    step.append(1)
                else:
                    infimum.append(list(value.values())[0][1]*0.8)
                    supremum.append(list(value.values())[0][1]*1.2)
                    step.append(list(value.values())[0][1]/1000)
        
        else:   # (2) Optimize without initial values
             infimum = [] # Set the optimization search space.
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
        self.scs_mdl_paths = scs_mdl_paths  # List of dictionaries with scs, mdl, and name entries.
        self.run_path = run_path
        self.ckt_name = ckt_name
        self.performance_goal = performance_goal    # Maps each metric name to its value and type metadata.
        self.params = params    # Corresponds to CircuitParams.params.
        self.wsub = wsub    # Corresponds to CircuitParams.wsub.
        self.print_flag = print_flag
        
        # Copy the MDL and SCS files into run_path/ckt_name.
        try:
            os.makedirs(os.path.join(run_path, ckt_name))
        except FileExistsError:
            pass
        
        # Remove stale SCS and MDL copies first.
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
        """Evaluate one candidate. Lower values are better; values below 1 meet all targets."""
        # Write the vector to the netlist.
        mdl_run_path = os.path.join(self.run_path, self.ckt_name)
        for scs_mdl_path in self.scs_mdl_paths:
            write_vector2netlist(self.params, x, self.wsub, f"{mdl_run_path}/TurBO_{scs_mdl_path['name']}.scs")
        
        # Run the simulation and read its metrics.
        present_performance = read_performance(mdl_run_path)
        
        # Calculate fitness.
        result = fitness_function_ABC(present_performance, self.performance_goal, self.print_flag)
        
        # TuRBO-M minimizes its objective; values below 1 mean that all targets have been met.
        # result = FITNESS_THRE/result  # reciprocal method, but subsequent convergence is too slow
        result = -result    # Use the supported direct sign inversion.
        
        return result
         
# fitness function, lower is better
class FitnessFunction_Prallel:
    
    def __init__(self, scs_mdl_paths, run_path, ckt_name, performance_goal, params, wsub, print_flag:bool = 1):
        self.scs_mdl_paths = scs_mdl_paths  # List of dictionaries with scs, mdl, and name entries.
        self.run_path = run_path
        self.ckt_name = ckt_name
        self.performance_goal = performance_goal    # Maps each metric name to its value, type, and relation metadata.
        self.params = params    # Corresponds to CircuitParams.params.
        self.wsub = wsub    # Corresponds to CircuitParams.wsub.
        self.print_flag = print_flag
        
        
        try:
            os.makedirs(os.path.join(run_path, ckt_name))
        except FileExistsError:
            # Clear prior per-candidate run directories.
            try:
                os.system(f'rm -rf {os.path.join(run_path, ckt_name)}/TurBO_*')
            except:
                pass
        
        
    def __call__(self, x:list[list[float]]) -> float:
        """Evaluate a candidate batch. Lower values are better; values below 1 meet all targets."""
        # Determine the degree of parallelism.
        n = len(x)
        
        mdl_run_paths = []
        
        # Copy SCS/MDL files into per-candidate directories and write each vector.
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
        
        # Run simulations and collect metrics in parallel.
        present_performances = read_multiple_performances(mdl_run_paths)
        
        results = []
        
        
        for present_performance in present_performances:
            # Calculate fitness.
            result = fitness_function_ABC(present_performance, self.performance_goal, self.print_flag)
            
            # TuRBO-M minimizes its objective; values below 1 mean that all targets have been met.
            # result = FITNESS_THRE/result  # reciprocal method, but subsequent convergence is too slow
            # print(result)
            result = -result    # Use the supported direct sign inversion.
            
            results.append([result])
        
        return results
        
        
circuit = CircuitParams(scs_mdl_paths[0]["scs"], technique_path, optimization_with_initial_flag)

dim = len(circuit.variables)

f_parallel = FitnessFunction_Prallel(scs_mdl_paths, run_path, ckt_name, performance_goal, circuit.params, circuit.wsub, 0)

Chat_Turbo1_Plus = Turbo1_Plus(
    f=f_parallel,
    lb=np.array(circuit.lb),
    ub=np.array(circuit.ub),
    n_init=2*dim,  # Initial points per trust region: 10 or 2 * dim.
    max_evals=99999,
    max_iters=100,
    batch_size=10,
    f_threshold=-1e4+1,
    x_init=initial_vector, # Alternatively, use circuit.vector.
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

# Save results.

try:
    os.makedirs(result_path)
except FileExistsError:
    pass

# Clear the result directory.
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
    # Insert the optimum into the SCS file.
    write_vector2netlist(circuit.params, x_best, circuit.wsub, f"{result_path}/{ckt_name}/TuBRO_{type_name}_result.scs")
    # Run the simulation.
    os.system(f'cd {result_path}/{ckt_name} && spectremdl -batch TuBRO_{type_name}_result.mdl -design TuBRO_{type_name}_result.scs +mt=3 >/dev/null && cat *.measure > result')
    # Delete generated files other than MDL, SCS, and result files.
    os.system(f'cd {result_path}/{ckt_name} && rm -rf *.log *.raw *.mt0 *.mt1 *.mt2 *.mt3 *.mt4')

# # Clear run_path/ckt_name after completion to avoid consuming disk space
# try:
#     os.system(f'rm -rf {run_path}/{ckt_name}/*')
# except:
#     pass