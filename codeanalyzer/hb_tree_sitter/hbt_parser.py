from tree_sitter import Language, Parser, Tree, Node
from codeanalyzer.hb_tree_sitter.hb_definition import TSHammockBlock, TSHBRelation
from typing import List, Optional
import codeanalyzer.hb_tree_sitter.hbt_python_rules as hbt_python_rules
import codeanalyzer.hb_tree_sitter.hbt_configs as hbt_configs
import tree_sitter_python as tspython
import os 
import pickle
import glob


class PyHbtParser:
    def __init__(self, source: str, filename: str, source_code_dir_list: list = [], parsing_mode: str = "rule-based"):
        self.block_map = {}  # block_id to TSHammockBlock
        self.tstree_map = {}  # source_file to tree-sitter tree
        self.pdg_map = {}  # source_file to PDGs
        self.parsing_mode = parsing_mode
        self.parsing_rules = None
        
        # Import the parsing rules based on the mode
        if self.parsing_mode not in ["rule-based", "default"]:
            raise ValueError(f"Unsupported parsing mode: {self.parsing_mode}")
        
        py_language = Language(tspython.language())
        self.parser = Parser(py_language)
        self.src_file_to_dir_map = {
            filename: os.path.dirname(filename)
        }
        if self.parsing_mode != "default":
            self.parsing_rules = hbt_python_rules.PythonTSHBParsingRules(source_code_dir_list, self.src_file_to_dir_map, cg_backend=hbt_configs.PY_CG_BACKEND)
        
        # Parse the source code files to create the tree-sitter trees from source files
        self._parse_source_code_to_ts_tree(source, filename)
        
        # Generate PDGs from the tree-sitter trees
        self._generate_pdg_from_ts_tree()

    def _parse_source_code_to_ts_tree(self, code_content: str, filename: str):
        code_content = code_content.rstrip('\n')
        code_content = bytes(code_content, "utf-8")
        tree = self.parser.parse(code_content)
        if tree.root_node.has_error:
            print(f"Error parsing source file {filename}. Skipping this file.")
            return
        if not len(code_content):
            print(f"Source file {filename} is empty. Skipping this file.")
            return
        self.tstree_map[filename] = tree
        return

    def _generate_pdg_from_ts_tree(self):
        for source_file, tree in self.tstree_map.items():
            print(f"Generating PDG for source file {source_file}...")
            pdg = self._generate_pdg_from_ts_tree_helper(tree, source_file)
            if pdg is not None:
                self.pdg_map[source_file] = pdg
            else:
                print(f"Failed to generate PDG for source file {source_file}.")
        return

    def _generate_pdg_from_ts_tree_helper(self, tree: Tree, source_file: str):
        # Walk tree-sitter trees to generate PDGs using tree-sitter tree cursor
        cursor = tree.walk()
        visited_children = False
        pdg = {
            "meta_data": {},
            "hammock_blocks": []
        }
        # first step, original tree traversal
        while True:
            if not visited_children:
                if cursor.node.is_named:
                    hammock_block, additional_blocks_list = self._construct_hammock_block_from_ts_node(cursor.node, source_file)
                    if hammock_block is not None:
                        hammock_block.meta_data["source_file"] = source_file
                        pdg["hammock_blocks"].append(hammock_block)
                        for additional_block in additional_blocks_list:
                            additional_block.meta_data["source_file"] = source_file
                            pdg["hammock_blocks"].append(additional_block)
                if not cursor.goto_first_child():
                    visited_children = True
            elif cursor.goto_next_sibling():
                visited_children = False
            elif not cursor.goto_parent():
                break
        # construct the children from hammock blocks
        self._construct_children_from_hammock_blocks(pdg["hammock_blocks"])
    
        # insert meta data, there are more fields to be added in other functions
        pdg["meta_data"]["source_file"] = source_file
        
        # post processing all hammock blocks
        self.parsing_rules._post_process_hammock_blocks(pdg, self.block_map)

        return pdg

    def _construct_hammock_block_from_ts_node(self, node: Node, source_file: str) -> Optional[TSHammockBlock]:
        # Process using default parsing rules and logics.
        if self.parsing_mode == "default":
            block_id = node.id 
            block_type = node.type
            start_point = node.start_point
            end_point = node.end_point
            
            # because we process the parent first, if a block has parent it will be in the block_map
            try:
                parent = self.block_map[node.parent.id] if node.parent else None
            except KeyError:
                # node has parent but parent is not in the block_map, this means that the parent is merged with its parent already, skip processing this block. 
                # note that this only works with default parsing mode because the skipped blocks are leaves in the tree-sitter tree
                print(f"Parent block {node.parent.id} not found in block_map. Skipping this block of type {node.type}, with start point: {start_point}, end point: {end_point}.")
                return None, []

            # default mode can only process comments, strings, and identifiers, and add them to parent blocks, we cannot process local variables as that requires inclusion/exclusion rules
            
            if block_type == "comment":
                comment = node.text.decode("utf-8")
                self.block_map[node.parent.id].comments.append(comment)
                return None, []
            elif block_type == "string":
                string = node.text.decode("utf-8")
                self.block_map[node.parent.id].string_literals.append(string)
                return None, []
            elif block_type == "identifier":
                indentifier = node.text.decode("utf-8")
                self.block_map[node.parent.id].local_identifiers.append(indentifier)
                return None, []
            else:
                # if the block is not a comment, string, or identifier, we create a hammock
                # we then defer the processing of the children to the post processing step due to pre-order traversal of the tree-sitter tree we do not have the children in map yet
                # we however do have the children ids
                children = []
                children_ids = []
                for child in node.named_children:
                    children_ids.append(child.id)
                hammock_block = TSHammockBlock(
                    block_id=block_id,
                    block_full_qualifier="",
                    block_type=block_type,
                    start_point=start_point,
                    end_point=end_point,
                    parent=parent,
                    children=children,
                    children_ids=children_ids,
                )
                
                # add block_id to the block_map for reference
                self.block_map[block_id] = hammock_block
                return hammock_block, []

        # Process using rules and logics.
        elif self.parsing_mode == "rule-based":
            block_id = node.id
            hammock_block, additional_blocks_list = self.parsing_rules.parse_ts_node(node, self.block_map, source_file)

            if hammock_block is not None:
                # Add block if not None
                assert block_id not in self.block_map, f"Block with id {block_id} already exists in block_map. This should not happen."
                self.block_map[block_id] = hammock_block
                # If the block has a parent we also establish the parent-child relationship
                current_parent = node.parent
                while current_parent is not None and current_parent.id not in self.block_map:
                    # If the parent is not in the block_map, we skip it and continue to the next parent
                    current_parent = current_parent.parent
                if current_parent is not None:
                    hammock_block.parent = self.block_map[current_parent.id]
                    if hammock_block.parent is not None and hammock_block.block_id not in hammock_block.parent.children_ids:
                        # Add the hammock block to the parent's children
                        hammock_block.parent.children_ids.append(block_id)
            else:
                # Otherwise this block is not relevant for the PDG
                parent_id = node.parent.id if node.parent else None
                if parent_id is not None and parent_id in self.block_map:
                    self.block_map[parent_id].discard_children_ids.append(block_id)
            return hammock_block, additional_blocks_list
 
    def _construct_children_from_hammock_blocks(self, hammock_blocks: List[TSHammockBlock]):
        if self.parsing_mode == "default":
            # Establish the children relationships
            for hammock_block in hammock_blocks:
                for child_id in hammock_block.children_ids:
                    if child_id in self.block_map:
                        hammock_block.children.append(self.block_map[child_id])
        elif self.parsing_mode == "rule-based":
            for hammock_block in hammock_blocks:
                present = set()
                for child_block in hammock_block.children:
                    hammock_block.children_ids.append(child_block.block_id)
                    present.add(child_block.block_id)
                    if child_block.block_id in hammock_block.discard_children_ids:
                        hammock_block.discard_children_ids = [id for id in hammock_block.discard_children_ids if id != child_block.block_id]
                for child_id in list(set(hammock_block.children_ids)):
                    if child_id not in present and child_id not in hammock_block.discard_children_ids:
                        # If the child_id is not present in the children, we add it to the children
                        if child_id in self.block_map:
                            hammock_block.children.append(self.block_map[child_id])
                        else:
                            print(f"Child block {child_id} not found in block_map. Skipping this child.")
                # Align the children_ids and discard_children_ids
                hammock_block.children_ids = list(set(hammock_block.children_ids) - set(hammock_block.discard_children_ids))                        
        else:
            raise ValueError(f"Unsupported parsing mode: {self.parsing_mode}.")
        return

    def get_full_pdg(self):
        return self.pdg_map

    def get_full_pdg_map(self, filename):
        return self.pdg_map.get(filename, None)
    
    def get_full_hbt_root(self, filename) -> Optional[TSHammockBlock]:
        if filename in self.pdg_map:
            pdg = self.pdg_map[filename]
            if pdg["hammock_blocks"]:
                if pdg["hammock_blocks"][0].block_type == "module":
                    return pdg["hammock_blocks"][0]
                else:
                    for i in range(1, len(pdg["hammock_blocks"])):
                        if pdg["hammock_blocks"][i].block_type == "module":
                            return pdg["hammock_blocks"][i]
        return None
        
    def get_pdg_from_source_file(self, source_file):
        if source_file in self.pdg_map:
            return self.pdg_map[source_file]
        else:
            print(f"Source file {source_file} not found in PDG map.")
            return None

    def get_matching_block_with_string(self, string_to_match: str) -> List[TSHammockBlock]:
        matching_blocks = []
        for block in self.block_map.values():
            if string_to_match in block.local_identifiers or string_to_match in block.string_literals:
                matching_blocks.append(block)
        return matching_blocks
    
    def get_code_snippet_from_hammock_block_id(self, block_id):
        if block_id not in self.block_map:
            return None
        block = self.block_map[block_id]
        source_file = block.meta_data["source_file"]
        start_line = block.start_point.row 
        end_line = block.end_point.row

        # Read the source file and extract lines
        try:
            with open(source_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            code_snippet = ''.join(lines[start_line:end_line + 1])
            return code_snippet 
        except FileNotFoundError:
            print(f"Source file {source_file} not found.")
            return None
        except Exception as e:
            print(f"Error reading source file {source_file}: {e}")
            return None

    def get_expanded_code_snippet_from_hammock_block_id(self, block_id):
        if block_id not in self.block_map:
            return None
        block = self.block_map[block_id]
        if block.parent is None:
            return ""
        return self.get_code_snippet_from_hammock_block_id(block.parent.block_id)

    def get_related_code_snippets_from_hammock_block_id(self, block_id):
        if block_id not in self.block_map:
            return None
        related_code_snippets = []
        for relation in self.block_map[block_id].relations:
            code_snippet = self.get_code_snippet_from_hammock_block_id(relation.target_block_id)
            if code_snippet is not None:
                related_code_snippets.append({
                    "code_snippet": code_snippet,
                    "relation": relation,
                })
            else:
                print(f"Code snippet for block ID {relation.target_block_id} not found.")
        return related_code_snippets

    def load_pdg_from_pickle(self, pkl_file_path: str):
        with open(pkl_file_path, 'rb') as f:
            pdg_data = pickle.load(f)
        self.pdg_map = pdg_data["pdg_map"]
        self.block_map = pdg_data["block_map"]
        self.tstree_map = pdg_data["tstree_map"]

    def save_pdg_to_pickle(self, pkl_file_path: str):
        with open(pkl_file_path, 'wb') as f:
            pdg_data = {
                "pdg_map": self.pdg_map,
                "block_map": self.block_map,
                "tstree_map": self.tstree_map
            }
            pickle.dump(pdg_data, f)
