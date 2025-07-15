import subprocess
import json
import os
import shutil
import codeanalyzer.hb_tree_sitter.codeql_utils.codeql_configs as codeql_configs


class CodeQLUtils:
    @staticmethod
    def run_command(command):
        """Runs a command and handles errors."""
        print(f"Executing: {' '.join(command)}")
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            print(f"Stdout: {result.stdout}")
            print(f"Stderr: {result.stderr}")
            print("Command successful.\n")
        except subprocess.CalledProcessError as e:
            print(f"Error running command: {e}")
            print(f"Stderr: {e.stderr}")
            print(f"Stdout: {e.stdout}")
            raise
    
    @staticmethod
    def construct_codeql_database_from_list(source_code_dir_list, artifact_dir, language):
        """
        Constructs a CodeQL database from a list of source code directories.
        """
        if not artifact_dir:
            artifact_dir = codeql_configs.DB_ARTIFACT_DIR
            os.makedirs(artifact_dir, exist_ok=True)
        assert os.path.exists(artifact_dir), f"Artifact directory does not exist: {artifact_dir}"
        db_name_map = {}
        for source_code_dir in source_code_dir_list:
            if not os.path.isdir(source_code_dir):
                raise ValueError(f"Source code directory does not exist: {source_code_dir}")
            db_name = artifact_dir + source_code_dir
            if os.path.exists(db_name):
                shutil.rmtree(db_name)
            os.makedirs(db_name, exist_ok=True)
            command = [
                "{}".format(codeql_configs.CODEQL_CMD), "database", "create", db_name,
                "--language={}".format(language),
                "--source-root=" + ",".join(source_code_dir_list)
            ]
            CodeQLUtils.run_command(command)
            db_name_map[source_code_dir] = db_name
        return db_name_map

    @staticmethod
    def get_caller_callee_edges(codeql_database, query_file=None):
        caller_callee_edges = []
        if not query_file:
            query_file = codeql_configs.DEFAULT_CG_QUERY_FILE_PY
        assert os.path.exists(codeql_configs.TMP_OUTPUT_DIR), f"Output directory does not exist: {codeql_configs.TMP_OUTPUT_DIR}"
        assert os.path.isfile(query_file)
        # Generate query output in BQRS format
        bqrs_output = os.path.join(codeql_configs.TMP_OUTPUT_DIR, "tmp-call-graph.bqrs")
        analyze_command = [
            "{}".format(codeql_configs.CODEQL_CMD), "query", "run",
            f"--database={codeql_database}",
            f"--output={bqrs_output}",
            query_file
        ]
        CodeQLUtils.run_command(analyze_command)
        
        # Decode the BQRS output to JSON
        json_output = os.path.join(codeql_configs.TMP_OUTPUT_DIR,"tmp-call-graph.json")
        decode_command = [
            "{}".format(codeql_configs.CODEQL_CMD), "bqrs", "decode",
            f"--output={json_output}",
            "--format=json",
            bqrs_output
        ]
        CodeQLUtils.run_command(decode_command)

        # Load and process the JSON results
        with open(json_output, 'r') as f:
            results = json.load(f)
            control_edges = results["#select"]["tuples"]
        for edge in control_edges:
            # Each edge is a tuple of (caller kind name, file location, callee kind name, file location) 
            ''' 
            Example:
                [["Function main","/root/Workspace/python-examples/simple_repo/main.py:6","Class Module1","/root/Workspace/python-examples/simple_repo/sub_folder1/module1.py:1"]
                ,["Function main","/root/Workspace/python-examples/simple_repo/main.py:7","Class Module2","/root/Workspace/python-examples/simple_repo/sub_folder1/module2.py:1"]
                ,["Function main","/root/Workspace/python-examples/simple_repo/main.py:8","Function add","/root/Workspace/python-examples/simple_repo/sub_folder1/module1.py:2"]
                ,["Function main","/root/Workspace/python-examples/simple_repo/main.py:9","Function add","/root/Workspace/python-examples/simple_repo/sub_folder1/module2.py:6"]
                ,["Function main","/root/Workspace/python-examples/simple_repo/main.py:10","Function add","/root/Workspace/python-examples/simple_repo/sub_folder1/module3.py:1"]
                ,["Function add","/root/Workspace/python-examples/simple_repo/sub_folder1/module1.py:4","Function helper","/root/Workspace/python-examples/simple_repo/sub_folder1/module1.py:6"]
                ,["Script main.py","/root/Workspace/python-examples/simple_repo/main.py:14","Function main","/root/Workspace/python-examples/simple_repo/main.py:5"]]
            '''
            caller_callee_edges.append(edge)
        return caller_callee_edges
