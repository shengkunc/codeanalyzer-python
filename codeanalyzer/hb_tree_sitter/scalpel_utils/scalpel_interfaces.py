import subprocess
import json
import os
import shutil
import codeanalyzer.hb_tree_sitter.scalpel_utils.scalpel_configs as scalpel_configs
from pprint import pprint
from scalpel.call_graph.pycg import CallGraphGenerator, formats
from collections import deque


class ScalpelUtils:
    @staticmethod
    def construct_scalpel_callgraphs_from_list(source_code_dir_list):
        cg_generator_map = {}
        for source_code_dir in source_code_dir_list:
            print(f"[SCALPEL] Constructing Scalpel call graph for source code directory: {source_code_dir}")
            entry_points = []
            for root, _, files in os.walk(source_code_dir):
                for file in files:
                    if file.endswith('.py'):
                        entry_points.append(os.path.join(root, file))
            entry_points.sort(key=len)
            cg_generator = CallGraphGenerator(entry_points, source_code_dir)
            cg_generator_map[source_code_dir] = cg_generator
        return cg_generator_map

    @staticmethod
    def get_caller_callee_edges(cg_generator, src_code_dir, pdg):
        cg_generator.analyze()
        edges = cg_generator.output_edges()
        internal_modules = cg_generator.output_internal_mods()
        caller_callee_edges = []
        for edge in edges:
            callee = edge[1]    
            found = False
            first_found_filename = None
            for module in internal_modules.keys():
                methods = internal_modules[module]["methods"]
                filename = internal_modules[module]["filename"]
                full_filename = os.path.join(src_code_dir, filename)
                assert os.path.isfile(full_filename), f"File does not exist: {full_filename}"
                for method in methods:
                    if methods[method]["name"] == callee:
                        if not found:
                            found = True
                            callee_line = int(methods[method]["first"])
                            first_found_filename = full_filename
                        else:
                            raise ValueError(f"Multiple methods with the full qualifier {callee} found in file {full_filename}, previous found in file {first_found_filename}.")
            if not found:
                print(f"Callee method {callee} not found in any internal modules, skipping.")
                continue
            # construct the callee information
            callee_type_name = "Function {}".format(callee)
            callee_location = "{}:{}".format(first_found_filename, callee_line)
            
            callersite = edge[0]
            found = False
            mod_level = False
            first_found_filename = None
            for module in internal_modules.keys():
                methods = internal_modules[module]["methods"]
                filename = internal_modules[module]["filename"]
                full_filename = os.path.join(src_code_dir, filename)
                assert os.path.isfile(full_filename), f"File does not exist: {full_filename}"
                for method in methods:
                    if methods[method]["name"] == callersite:
                        if not found:
                            found = True
                            callsite_line_start = int(methods[method]["first"])
                            callsite_line_end = int(methods[method]["last"])
                            first_found_filename = full_filename
                            if callersite == module:
                                mod_level = True
                        else:
                            raise ValueError(f"Multiple methods with the full qualifier {callersite} found in file {full_filename}, previous found in file {first_found_filename}.")
            if not found:
                print(f"Caller method {callersite} not found in any internal modules, skipping.")
                continue
            if mod_level:
                caller_type_name = "Script {}".format(os.path.basename(first_found_filename))
            else:
                caller_type_name = "Function {}".format(callersite)
            callsite_seachrange = (callsite_line_start, callsite_line_end)
            callsite_approx = ScalpelUtils._get_approx_callsite(callsite_seachrange, callersite, callee, pdg, mod_level)
            if callsite_approx is None:
                print(f"Callsite {callersite} not found in PDG, skipping.")
                continue
            if not isinstance(callsite_approx, set):
                caller_location = "{}:{}".format(first_found_filename, callsite_approx)
                caller_callee_edges.append(
                    [caller_type_name, caller_location, callee_type_name, callee_location]
                )
            else:
                for refined_start_point in callsite_approx:
                    caller_location = "{}:{}".format(first_found_filename, refined_start_point)
                    caller_callee_edges.append(
                        [caller_type_name, caller_location, callee_type_name, callee_location]
                    )
        return caller_callee_edges
            
    @staticmethod
    def _get_approx_callsite(callsite_seachrange, callersite, callee, pdg, mod_level):
        # identify the exact corsa hammock block line that mathces the callsite
        basic_start_point = None
        default_start_block = None
        for block in pdg["hammock_blocks"]:
            if block.start_point[0] + 1 == callsite_seachrange[0] and block.end_point[0] + 1 == callsite_seachrange[1]:
                if block.block_full_qualifier == callersite:
                    basic_start_point = block.start_point[0] + 1
                    default_start_block = block
        # If no match found, some thing is wrong and worth investigating
        if basic_start_point is None:
            return None

        # refine the start point by searching the block map using BFS
        all_callsites_blocks = []
        queue = deque([default_start_block])
        visited = set()
        while queue:
            current_block = queue.popleft()
            if current_block.block_id in visited:
                continue
            visited.add(current_block.block_id)
            if len(current_block.local_callsites) > 0:
                if mod_level:
                    if current_block.parent is not None and current_block.parent.block_full_qualifier == callersite:
                        all_callsites_blocks.append(current_block)
                else:
                    all_callsites_blocks.append(current_block)
            for child in current_block.children:
                if child.block_id not in visited:
                    queue.append(child)
        set_match = set()
        refined_start_points = set()
        for block in all_callsites_blocks:
            callsites = block.local_callsites
            for callsite in callsites:
                callee_funcname = callsite[1].split(".")[-1]
                if callee_funcname == callee.split(".")[-1]:
                    set_match.add(callsite[1])
                    refined_start_points.add(block.start_point[0] + 1)
        
        # this is strict, we only return the refined start point if there is exactly one match, if not, there are ambiguities, we return the basic start point
        return refined_start_points if (refined_start_points is not None and (len(set_match) == 1 or len(refined_start_points) == 1)) else basic_start_point
    