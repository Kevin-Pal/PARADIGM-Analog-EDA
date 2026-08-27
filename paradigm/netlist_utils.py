import numpy as np
import re, json, os
import subprocess, time
from math import sqrt, log10
import csv

import torch

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

        if 'not' in line:# Bias transistors and bias resistors must remain unchanged.
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

def make_fitness_function(
    GBW_weight,
    Gain_weight,
    Pdiss_weight)->callable:
    """Build a weighted fitness function compatible with fitness_function_ABC.

    Weights 1, 0, and -1 apply the identity, square-root, and log10 transforms, respectively. op_tgt is retained for interface compatibility."""
    def fitness_function(
        result:dict[str:float],
        op_tgt:dict[str:float],
        print_flag:bool = 0
    )->float:
        try:
            # print(result)
            dc_gain = float(result["DC_gain"])
            GBW_VOUT = float(result["GBW_VOUT"])
            PM_VOUT = float(result["PM_VOUT"])
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
            
            # Unused argument opt_tgt
            # dc_gain_require = op_tgt["DC_gain"]
            # PM_VOUT_require = op_tgt["PM_VOUT"]
        except:
            print("\033[31mError: The result dictionary does not contain the required keys.\033[0m")
            return None
        
        fitness = 0
        
        # Detect circuit anomalies and apply a penalty.
        if np.isnan(dc_gain) or np.isnan(GBW_VOUT) or np.isnan(PM_VOUT) or np.isnan(Pdiss):
            fitness += 1
            if print_flag:
                print(f"DC_gain, GBW_VOUT, PM_VOUT, or Pdiss is NaN")
                 
        if PM_VOUT > 90 or PM_VOUT < 60:
            fitness += 1
            if print_flag:
                print(f"PM_VOUT is not in the range of 60 to 90")
        
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
        # if gm2 is not None and gm3 is not None:
        #     if gm2 > gm3:
        #         fitness += 1
        #         if print_flag:
        #             print(f"gm2 is larger than gm3")
        # UGB_GBW_max = max(UGB,GBW_VOUT)
        # UGB_GBW_min = min(UGB,GBW_VOUT)
        # if  UGB_GBW_min < UGB_GBW_max * 0.9:
        #     fitness += 1
        #     # # Skip this comparison for SMC for now
        #     # if ckt_name == 'SMC':
        #     #     fitness -= 1
        #     if print_flag:
        #         print(f"UGB is much too different from GBW")
        
        if fitness == 0:
            # No anomaly was found; compute the weighted fitness.
            # Compute using lg [ (GBW/10^(Gain/20)) * 10^(Gain/20) / Pdiss ]
            # Apply square-root or log10 transforms to the three terms according to their weights
            
            # 1016 update: computing fitness as GBW * 10^(Gain/20) / Pdiss with different weights may be more reasonable
            # Added weights 2, 3, and 4 for log10(GBW), sqrt(GBW), and the original calculation, respectively
            if GBW_weight == 0:
                A = sqrt(GBW_VOUT/10**(dc_gain/20))
            elif GBW_weight == -1:
                A = log10(GBW_VOUT/10**(dc_gain/20))
            elif GBW_weight == 1:
                A = GBW_VOUT/10**(dc_gain/20)
            elif GBW_weight == 2:
                A = log10(GBW_VOUT)
            elif GBW_weight == 3:
                A = sqrt(GBW_VOUT)
            else:
                A = GBW_VOUT
                
            if Gain_weight == 0:
                B = sqrt(10**(dc_gain/20))
            elif Gain_weight == -1:
                B = log10(10**(dc_gain/20))
            else:
                B = 10**(dc_gain/20)
                
            if Pdiss_weight == 0:
                C = sqrt(Pdiss)
            elif Pdiss_weight == -1:
                C = 1/(log10(1/Pdiss))
            else:
                C = Pdiss
                
            fitness = A * B / C
            
            if fitness <= 0:
                # This may still indicate an anomaly
                # For example, A may be below 1 and become negative after logging, or another measured parameter may be zero; in either case the log below is undefined
                fitness = -1  
            else:
                fitness = log10(fitness)
                
        else:
            # An anomalous design receives a negative fitness.
            fitness = -fitness

        return fitness
    
    return fitness_function

def num_of_pareto_optimal_points_in_database(database_path:str)->int:
    """Count database rows whose solution path is not marked STALE."""
    csv_path = database_path + "/result.csv"
    num = 0
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        csv_reader = csv.reader(csvfile)
        header = next(csv_reader)
        for row in csv_reader:
            if row[7] != "STALE":
                # Any point not marked STALE is Pareto-optimal.
                num += 1
    return num

def collect_dominated_points_from_database(performance:dict[str:float],
        database_path:str,
    )->list[list]:
    """Return database rows dominated by the supplied performance point, including STALE rows."""
    csv_path = database_path + "/result.csv"
    try:
        GBW = performance["GBW_VOUT"]
        Gain = performance["DC_gain"]
        Pdiss = performance["Pdiss"]
    except:
        print("\033[31mError: The performance dictionary does not contain the required keys.\033[0m")
        return []
    dominated_points = []
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        csv_reader = csv.reader(csvfile)
        header = next(csv_reader)
        for row in csv_reader:
            if float(row[0]) < GBW and float(row[1]) < Gain and float(row[2]) > Pdiss:
                dominated_points.append(row)
                
    return dominated_points

def collect_dominant_points_from_database(performance:dict[str:float],
        database_path:str,
    )->list[list]:
    """Return database rows that dominate the supplied performance point, including STALE rows."""
    csv_path = database_path + "/result.csv"
    try:
        GBW = performance["GBW_VOUT"]
        Gain = performance["DC_gain"]
        Pdiss = performance["Pdiss"]
    except:
        print("\033[31mError: The performance dictionary does not contain the required keys.\033[0m")
        return []
    dominant_points = []
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        csv_reader = csv.reader(csvfile)
        header = next(csv_reader)
        for row in csv_reader:
            if float(row[0]) > GBW and float(row[1]) > Gain and float(row[2]) < Pdiss:
                dominant_points.append(row)
                
    return dominant_points
    
FITNESS_THRE = 100 # Fitness threshold; larger values indicate an anomaly.
    
def fitness_function_multiobj_check_no(result:dict[str:float],
        database_path:str,
        print_flag:bool = 0
    )->float:
    """Evaluate multi-objective fitness directly from Pareto dominance.

    This variant considers only GBW, Gain, and Pdiss and does not check constraints or anomalies. Lower values are better."""
    try:
        # print(result)
        dc_gain = float(result["DC_gain"])
        GBW_VOUT = float(result["GBW_VOUT"])
        Pdiss = float(result["Pdiss"])
    except:
        print("\033[31mError: The result dictionary does not contain the required keys.\033[0m")
        return None
    
    # Read the database
    N_pareto_optimal = num_of_pareto_optimal_points_in_database(database_path)
    points_dominate_input = collect_dominant_points_from_database(result, database_path)
    
    if len(points_dominate_input) == 0: # The current point is Pareto-optimal.
        # fitness is (the number of points dominated by this point + 1) / (the total number of Pareto-optimal points + 1)
        point_dominated_by_input = collect_dominated_points_from_database(result, database_path)
        fitness = (1 + len(point_dominated_by_input)) / (N_pareto_optimal + 1)
    else: # The current point is not Pareto-optimal.
        # fitness is 1 plus the sum of the fitness values of points that dominate this point
        fitness = 1
        for point in points_dominate_input:
            point_performance = {
                "GBW_VOUT":float(point[0]),
                "DC_gain":float(point[1]),
                "Pdiss":float(point[2])
            }
            fitness += fitness_function_multiobj_check_no(point_performance, database_path)    
            if fitness > FITNESS_THRE:
                break # Stop early to avoid excessively deep recursion
            # Consider caching information later; with many points this step can repeatedly recurse too deeply
            
        fitness = min(fitness, FITNESS_THRE-1)
    
    return fitness
    

def fitness_function_multiobj(result:dict[str:float],
        database_path:str,
        print_flag:bool = 0
    )->float:
    """Evaluate multi-objective fitness directly from Pareto dominance.

    Comparison points come from the database rather than intermediate optimizer state. Lower values are better."""
    try:
        # print(result)
        dc_gain = float(result["DC_gain"])
        GBW_VOUT = float(result["GBW_VOUT"])
        PM_VOUT = float(result["PM_VOUT"])
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
        
        # Unused argument opt_tgt
        # dc_gain_require = op_tgt["DC_gain"]
        # PM_VOUT_require = op_tgt["PM_VOUT"]
    except:
        print("\033[31mError: The result dictionary does not contain the required keys.\033[0m")
        return None
    
    fitness = 0
    
    # Detect circuit anomalies and apply a penalty.
    if np.isnan(dc_gain) or np.isnan(GBW_VOUT) or np.isnan(PM_VOUT) or np.isnan(Pdiss):
        fitness += 1
        if print_flag:
            print(f"DC_gain, GBW_VOUT, PM_VOUT, or Pdiss is NaN")
                
    if PM_VOUT > 90 or PM_VOUT < 60:
        fitness += 1
        if print_flag:
            print(f"PM_VOUT is not in the range of 60 to 90")
    
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
    
    fitness = fitness * FITNESS_THRE
    
    if fitness != 0:
        return fitness
    
    # Read the database
    N_pareto_optimal = num_of_pareto_optimal_points_in_database(database_path)
    points_dominate_input = collect_dominant_points_from_database(result, database_path)
    
    if len(points_dominate_input) == 0: # The current point is Pareto-optimal.
        # fitness is (the number of points dominated by this point + 1) / (the total number of Pareto-optimal points + 1)
        point_dominated_by_input = collect_dominated_points_from_database(result, database_path)
        fitness = (1 + len(point_dominated_by_input)) / (N_pareto_optimal + 1)
    else: # The current point is not Pareto-optimal.
        # fitness is 1 plus the sum of the fitness values of points that dominate this point
        fitness = 1
        for point in points_dominate_input:
            point_performance = {
                "GBW_VOUT":float(point[0]),
                "DC_gain":float(point[1]),
                "Pdiss":float(point[2])
            }
            fitness += fitness_function_multiobj_check_no(point_performance, database_path) # Reuse the companion function because no further stability check is needed.
            if fitness > FITNESS_THRE:
                break # Stop early to avoid excessively deep recursion
            # Consider caching information later; with many points this step can repeatedly recurse too deeply
            
        fitness = min(fitness, FITNESS_THRE-1)
    
    return fitness
    
def is_a_valuable_solution(result:dict[str:float], print_flag:bool = 0)->bool:
    """Check DC_gain, GBW_VOUT, PM_VOUT, and Pdiss for invalid or anomalous values."""
    try:
        # print(result)
        dc_gain = float(result["DC_gain"])
        GBW_VOUT = float(result["GBW_VOUT"])
        PM_VOUT = float(result["PM_VOUT"])
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
        
        # Unused argument opt_tgt
        # dc_gain_require = op_tgt["DC_gain"]
        # PM_VOUT_require = op_tgt["PM_VOUT"]
    except:
        print("\033[31mError: The result dictionary does not contain the required keys.\033[0m")
        return False
    
    fitness = 0
    
    # Detect circuit anomalies and apply a penalty.
    if np.isnan(dc_gain) or np.isnan(GBW_VOUT) or np.isnan(PM_VOUT) or np.isnan(Pdiss):
        fitness += 1
        if print_flag:
            print(f"DC_gain, GBW_VOUT, PM_VOUT, or Pdiss is NaN")
                
    if PM_VOUT > 90 or PM_VOUT < 60:
        fitness += 1
        if print_flag:
            print(f"PM_VOUT is not in the range of 60 to 90")
    
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
    
    if fitness != 0:
        # An anomaly is present.
        return False
    else:
        # No anomaly is present.
        return True
    

def add_datapoint2database(
    full_database_path:str,
    performance:dict[str:float],
    fitness,
    performance_weight,
    solution_vector,    # When writing this to CSV, the array must be space-separated; generally str(np.array) works but str(list) does not
    solution_full_path:str,
    print_flag:bool = 0
):
    """Admit a simulated point to the Pareto database.

    Dominated existing rows are marked STALE; a dominated new point is skipped; otherwise the new point and its evidence path are appended."""
    # Read the key metrics GBW_VOUT, DC_gain, and Pdiss.
    try:
        GBW = performance["GBW_VOUT"]
        Gain = performance["DC_gain"]
        Pdiss = performance["Pdiss"]
    except:
        print("\033[31mError: The performance dictionary does not contain the required keys.\033[0m Cannot add the datapoint to the database.")
        return None
    csv_path = full_database_path + "/result.csv"
    
    # NOTE: No longer use fitness to decide whether to add a point; use the metrics in performance directly
    # # fitness may also be NaN; treat it as an anomaly and do not add the point
    # if np.isnan(fitness):
    #     return False
    
    # # A positive fitness indicates an anomaly; do not add the point
    # if fitness > 0:
    #     return False
    
    # # A negative fitness indicates no anomaly; begin adding the point
    
    if is_a_valuable_solution(performance, print_flag) == False:
        # Reject anomalous solutions.
        if print_flag:
            print(f"The solution is not valuable, not adding to the database.")
        return False
    
    # CSV header: GBW, Gain, Pdiss, Fitness, time, performance weight, solution vector, solution path
    else:
        buffer_data = []
        
        with open(csv_path, newline='', encoding='utf-8') as csvfile:
            csv_reader = csv.reader(csvfile)
            
            # Read the CSV header.
            header = next(csv_reader)
            buffer_data.append(header)
            
            # Process rows one at a time.
            for row in csv_reader:
                # Skip blank rows.
                if len(row) == 0:
                    continue
                # The new data is dominated by every existing database point; do not add it and exit
                if float(row[0]) > GBW and float(row[1]) > Gain and float(row[2]) < Pdiss:
                    if print_flag:
                        print(f"The new data ({GBW},{Gain},{Pdiss}) is inferior to the existing data ({row[0]},{row[1]},{row[2]}). Ignored.")
                    return False
                # The new data dominates every existing database point; delete the folder at row[7] and mark that entry as STALE
                elif float(row[0]) < GBW and float(row[1]) < Gain and float(row[2]) > Pdiss:
                    if print_flag:
                        print(f"The new data ({GBW},{Gain},{Pdiss}) is superior to the existing data ({row[0]},{row[1]},{row[2]}). Deleting the existing data.")
                    if os.path.exists(row[7]):
                        os.system(f'rm -rf {row[7]}')
                    row[7] = "STALE"
                    # Preserve this record for provenance.
                    buffer_data.append(row)
                # The new point overlaps an existing point; retain both and continue.
                else:
                    buffer_data.append(row)
            
            # If no existing point dominates the new one, append it to buffer_data.
            # First copy result and *.scs from solution_full_path (TurBO_i) to full_database_path/result_folder/{_time}
            _time = time.strftime("%Y-%m%d-%H%M%S", time.localtime())
            os.system(f'mkdir -p {full_database_path}/result_folder/{_time}')
            os.system(f'cp {solution_full_path}/result {full_database_path}/result_folder/{_time}')
            os.system(f'cp {solution_full_path}/*.scs {full_database_path}/result_folder/{_time}')
            # Append the new point.
            buffer_data.append([GBW,Gain,Pdiss,fitness,_time,performance_weight,solution_vector,f"{full_database_path}/result_folder/{_time}"])
            if print_flag:
                print(f"New data added to the database.")
            
        # Write buffer_data back to the CSV file.
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            csv_writer = csv.writer(csvfile)
            csv_writer.writerows(buffer_data)
            
        return True
                
    
            
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
            
# Fitness-function wrapper.
# Input: one vector; output: one scalar. Parallel execution is not supported.
# Uses the built-in fitness calculation.
# Lower values are better.
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
         
# Fitness-function wrapper.
# Input: a candidate matrix; output: an objective vector. Parallel execution is supported.
# Uses the built-in fitness calculation.
# Lower values are better.
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
    
# Fitness-function wrapper.
# Input: a candidate matrix; output: an objective vector. Parallel execution is supported.
# Accepts a caller-supplied fitness function whose raw value is maximized.
# FitnessFunction_Prallel_Tailor negates that value for minimization.
# Tailored wrapper for database-building runs.
class FitnessFunction_Prallel_Tailor:
    
    def __init__(self, scs_mdl_paths, run_path, ckt_name, performance_goal, params, wsub, fitness_function:callable, database_path, performance_weight, print_flag:bool = 0):
        self.scs_mdl_paths = scs_mdl_paths  # List of dictionaries with scs, mdl, and name entries.
        self.run_path = run_path    # Simulation root, excluding ckt_name.
        self.ckt_name = ckt_name
        self.performance_goal = performance_goal    # Maps each metric name to its value, type, and relation metadata.
        self.params = params    # Corresponds to CircuitParams.params.
        self.wsub = wsub    # Corresponds to CircuitParams.wsub.
        self.print_flag = print_flag
        self.fitness_function = fitness_function    # Fitness callable with the interface fitness_function(present_performance, performance_goal, print_flag).
        self.database_path = database_path  # Database root, excluding ckt_name.
        self.performance_weight = performance_weight    # Boolean importance mask ordered as [GBW, Gain, Pdiss].
        
        try:
            os.makedirs(os.path.join(run_path, ckt_name))
        except FileExistsError:
            # Clear prior per-candidate run directories.
            try:
                os.system(f'rm -rf {os.path.join(run_path, ckt_name)}/TurBO_*')
            except:
                pass
        
        
    def __call__(self, x:list[list[float]]) -> float:
        """Evaluate a candidate batch with the caller-supplied fitness function. Lower values are better."""
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
                
        # Calculate fitness.
        results = []
        
        for present_performance in present_performances:
            # Calculate fitness.
            result = self.fitness_function(present_performance, self.performance_goal, self.print_flag)
            
            # TuRBO-M minimizes its objective; values below 1 mean that all targets have been met.
            # result = FITNESS_THRE/result  # reciprocal method, but subsequent convergence is too slow
            # print(result)
            result = -result    # Use the supported direct sign inversion.
            
            results.append([result])
            
        # Add points to the database.
        # Data lineage:
        # x[i] (solution vector) -> present_performances[i] (performance) -> result[i] (fitness) -> mdl_run_paths[i] (result and scs files)
        full_database_path = os.path.join(self.database_path, self.ckt_name)
        for i in range(n):
            add_datapoint2database(full_database_path, present_performances[i], results[i][0], self.performance_weight, x[i], mdl_run_paths[i])
        
        return results 
    
# Fitness-function wrapper.
# Input: a candidate matrix; output: an objective vector. Parallel execution is supported.
# Uses fitness_function_multiobj.
# Lower fitness is better.
class FitnessFunction_Prallel_Multiobj:
    
    def __init__(self, scs_mdl_paths, run_path, ckt_name, params, wsub, database_path, performance_weight, print_flag:bool = 0):
        self.scs_mdl_paths = scs_mdl_paths  # List of dictionaries with scs, mdl, and name entries.
        self.run_path = run_path    # Simulation root, excluding ckt_name.
        self.ckt_name = ckt_name
        self.params = params    # Corresponds to CircuitParams.params.
        self.wsub = wsub    # Corresponds to CircuitParams.wsub.
        self.print_flag = print_flag
        self.database_path = database_path  # Database root, excluding ckt_name.
        self.performance_weight = performance_weight    # Label describing the fitness mode, such as “second-order optimization”.
        
        try:
            os.makedirs(os.path.join(run_path, ckt_name))
        except FileExistsError:
            # Clear prior per-candidate run directories.
            try:
                os.system(f'rm -rf {os.path.join(run_path, ckt_name)}/TurBO_*')
            except:
                pass
        
        
    def __call__(self, x:list[list[float]]) -> float:
        """Evaluate a candidate batch by Pareto dominance. Lower values are better."""
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
                
        # Calculate fitness.
        results = []
        
        for present_performance in present_performances:
            # Calculate fitness.
            result = fitness_function_multiobj(present_performance, self.database_path + f"/{self.ckt_name}", self.print_flag)
            
            results.append([result])
            
        # Add points to the database.
        # Data lineage:
        # x[i] (solution vector) -> present_performances[i] (performance) -> result[i] (fitness) -> mdl_run_paths[i] (result and scs files)
        full_database_path = os.path.join(self.database_path, self.ckt_name)
        for i in range(n):
            add_datapoint2database(full_database_path, present_performances[i], results[i][0], self.performance_weight, x[i], mdl_run_paths[i])
        
        return results

def read_GBW_Gain_Pdiss_from_dict(performance:dict[str:float]):
    """Return GBW, Gain, and Pdiss from a performance dictionary."""
    
    # # NOTE: For now, simulations during step-three P2C_Net training ignore invalid solutions because the inputs should be reasonable; handle invalid solutions later if needed, for example by assigning special values to GBW, `Gain`, and `Pdiss`, while noting the possible impact on loss calculation
    # if is_a_valuable_solution(performance) == False:
    #     pass
    
    try:
        GBW = performance["GBW_VOUT"]
        Gain = performance["DC_gain"]
        Pdiss = performance["Pdiss"]
    except:
        print("\033[31mError: The performance dictionary does not contain the required keys.\033[0m")
        return None
    
    return GBW, Gain, Pdiss
    
# Circuit-parameters-to-performance simulator.
# Input: batch_num × dim_CircuitParameters; output: batch_num × dim_Performance.
# Run all simulations in parallel.
class C2P_Simulator:
    """Map batches of circuit parameters to simulated performance metrics.

    Input tensors follow CircuitParams.params. Outputs are ordered as GBW (Hz), Gain (dB), and Pdiss (W). PM, GM, and SR are checked only when admitting a point to the database."""
    def __init__(self, scs_mdl_paths, run_path, ckt_name, params, wsub, database_path, performance_weight, print_flag:bool = 0, Save2Database_flag:bool = 0):
        
        self.scs_mdl_paths = scs_mdl_paths  # List of dictionaries with scs, mdl, and name entries.
        self.run_path = run_path    # Simulation root, excluding ckt_name.
        self.ckt_name = ckt_name
        self.params = params    # Corresponds to CircuitParams.params.
        self.wsub = wsub    # Corresponds to CircuitParams.wsub.
        self.print_flag = print_flag
        self.database_path = database_path  # Database root, excluding ckt_name.
        self.performance_weight = performance_weight    # Label describing the fitness mode, such as “second-order optimization”.
        self.Save2Database_flag = Save2Database_flag    # Whether to save simulation results to the database; enabling this adds overhead.
        
        try:
            os.makedirs(os.path.join(run_path, ckt_name))
        except FileExistsError:
            # Clear prior per-candidate run directories.
            try:
                os.system(f'rm -rf {os.path.join(run_path, ckt_name)}/TurBO_*')
            except:
                pass
            
    def __call__(self, x:torch.Tensor, target_perf_dim=None) -> torch.Tensor:
        """Simulate a parameter batch and return a tensor of selected performance metrics."""
        # Determine the degree of parallelism.
        n = x.shape[0]
        
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
        
        # Build a tensor of GBW (Hz), Gain (dB), and Pdiss (W).
        results = []
        for present_performance in present_performances:
            # Calculate fitness.
            result = read_GBW_Gain_Pdiss_from_dict(present_performance)
            results.append(result)
        results = torch.tensor(results)
        
        # Add points to the database.
        if self.Save2Database_flag:
            # Data lineage:
            # x[i] (solution vector) -> present_performances[i] (performance) -> result[i] (fitness) -> mdl_run_paths[i] (result and scs files)
            full_database_path = os.path.join(self.database_path, self.ckt_name)
            for i in range(n):
                # Convert the tensor to a NumPy array.
                solution_vector = str(x[i].numpy())
                add_datapoint2database(full_database_path, present_performances[i], "C2P_Simulator", self.performance_weight, solution_vector, mdl_run_paths[i])

        return results