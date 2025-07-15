        # Construct the data relation edges
        # self._construct_data_relation_edges()
        
        # Construct the caller-callee relation edges
        # self._construct_caller_callee_relation_edges()
        
        # Construct the local variables inherentance relations
        # self._inhereit_children_shared_locals()



def _construct_data_relation_edges(self):
        for _, pdg in self.pdg_map.items():
            hammock_blocks = pdg["hammock_blocks"]
            if self.parsing_mode == "default":
                # in default mode, only identifiers are used to construct data relation edges
                for i in range(len(hammock_blocks)):
                    for j in range(len(hammock_blocks)):
                        if i != j:
                            # check if the two blocks are related by identifiers
                            hammock_block_i = hammock_blocks[i]
                            hammock_block_j = hammock_blocks[j]
                            shared_identifiers = set(hammock_block_i.local_identifiers) & set(hammock_block_j.local_identifiers)
                            if len(shared_identifiers):
                                # construct the relation
                                relation = Relation(
                                    relation_type="data",
                                    target_block_id=hammock_block_j.block_id,
                                    functional_description="Data relation between {} and {}".format( hammock_block_i.block_id, hammock_block_j.block_id),
                                    target_block_type=hammock_block_j.block_type,
                                    related_variables=list(shared_identifiers)
                                )
                                hammock_block_i.relations.append(relation)
            elif self.parsing_mode == "rule-based":
                # in default mode, variables are used to construct data relation edges
                for i in range(len(hammock_blocks)):
                    for j in range(len(hammock_blocks)):
                        if i != j:
                            # check if the two blocks are related by identifiers
                            hammock_block_i = hammock_blocks[i]
                            hammock_block_j = hammock_blocks[j]
                            shared_locals = set(hammock_block_i.local_variables) & set(hammock_block_j.local_variables)
                            if len(shared_locals):
                                # construct the relation
                                relation = Relation(
                                    relation_type="data",
                                    target_block_id=hammock_block_j.block_id,
                                    functional_description="Data relation between {} and {}".format( hammock_block_i.block_id, hammock_block_j.block_id),
                                    target_block_type=hammock_block_j.block_type,
                                    related_variables=list(shared_locals)
                                )
                                hammock_block_i.relations.append(relation)
            else:
                raise ValueError(f"Unsupported parsing mode: {self.parsing_mode}.")

    def _inhereit_children_shared_locals(self):
        for _, pdg in self.pdg_map.items():
            hammock_blocks = pdg["hammock_blocks"]
            if self.parsing_mode in ["default", "rule-based"]:
                # inherit all identifiers, strings, and variables from descendants
                def inherit_from_descendants(block: TSHammockBlock, visited: set):
                    if block.block_id in visited:
                        return
                    visited.add(block.block_id)
                    
                    # First process all children recursively
                    for child in block.children:
                        inherit_from_descendants(child, visited)
                        
                        # Then inherit from each child
                        for identifier in child.local_identifiers:
                            block.local_identifiers.append(identifier)
                        
                        for string_literal in child.string_literals:
                            block.string_literals.append(string_literal)
                        
                        for variable in child.local_variables:
                            block.local_variables.append(variable)

                # Apply inheritance ONLY starting from root nodes (nodes without parents)
                visited = set()
                for hammock_block in hammock_blocks:
                    if hammock_block.parent is None and hammock_block.block_id not in visited:
                        inherit_from_descendants(hammock_block, visited)
                for hammock_block in hammock_blocks:
                    # Remove duplicates from local identifiers, string literals, and local variables
                    hammock_block.local_identifiers = list(set(hammock_block.local_identifiers))
                    hammock_block.string_literals = list(set(hammock_block.string_literals))
                    hammock_block.local_variables = list(set(hammock_block.local_variables))
            else:
                raise ValueError(f"Unsupported parsing mode: {self.parsing_mode}.")
    
    def _construct_caller_callee_relation_edges(self):
        self.parsing_rules._construct_caller_callee_relation_edges(self.block_map, self.pdg_map)

    def _construct_control_relation_edges(self):
        raise RuntimeError("Not sure if this is needed, put it here now as a placeholder.")
    