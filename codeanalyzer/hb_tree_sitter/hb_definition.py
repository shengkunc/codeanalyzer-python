from dataclasses import dataclass, field
from typing import List, Optional
from tree_sitter import Point

@dataclass
class TSHammockBlock:
    meta_data: dict = field(default_factory=dict)
    block_id: str = ""
    block_full_qualifier: str = ""
    project_full_qualifier: str = ""
    block_type: str = ""
    start_point: Optional[Point] = None
    end_point: Optional[Point] = None
    children_ids: List[str] = field(default_factory=list)
    discard_children_ids: List[str] = field(default_factory=list)
    children: List['TSHammockBlock'] = field(default_factory=list)
    parent: Optional['TSHammockBlock'] = None
    local_variables: List[str] = field(default_factory=list)
    string_literals: List[str] = field(default_factory=list)
    local_identifiers: List[str] = field(default_factory=list)
    local_callsites: List[str] = field(default_factory=list)
    imported_packages: List[str] = field(default_factory=list)
    comments: List[str] = field(default_factory=list)
    relations: List['TSHBRelation'] = field(default_factory=list)


@dataclass
class TSHBRelation:
    relation_type: str = ""
    target_block_id: str = ""
    target_block_full_qualifier: str = ""
    functional_description: str = ""
    target_block_type: str = ""
    related_variables: List[str] = field(default_factory=list)
