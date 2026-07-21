#!/usr/bin/env python3

import argparse
import datetime
import glob
import os
import shlex
import subprocess
import sys


sys.path.append(os.path.join(os.environ["CMSSW_BASE"], "python"))


JERC_BASE = "/afs/hep.wisc.edu/home/mithakor/HH_bb_tautau_Analysis/JEC_JER/CMSSW_15_0_5/src/JEC_JER"


def normalize_path(p):
    if p.startswith("/hdfs/"):
        return "root://cmsxrootd.hep.wisc.edu/" + p[len("/hdfs"):]
    return p


def collect_input_files(args):
    if args.inputList:
        with open(args.inputList, "r", encoding="utf-8") as input_handle:input_files = [line.strip() for line in input_handle if (line.strip() and not line.lstrip().startswith("#"))]
        print(f"Using {len(input_files)} files from list {args.inputList}")

    elif args.inputDir:
        input_files = sorted(glob.glob(os.path.join(args.inputDir, "*.root")))
        print(f"Found {len(input_files)} input files in {args.inputDir}")

    else:
        raise RuntimeError("Provide either --inputDir or --inputList.")

    input_files = [normalize_path(path) for path in input_files]

    if not input_files:
        raise RuntimeError("No input ROOT files were found.")

    return input_files


def get_extra_inputs(year):
    paths = [
        os.path.join(JERC_BASE,"jerc_module.py"),
        os.path.join(JERC_BASE,"jerc_config.py"),
        os.path.join(JERC_BASE,"JecConfigAK4.json"),
        os.path.join(JERC_BASE,"JecConfigAK8.json"),
        os.path.join(JERC_BASE,"metadata",year,"jet_jerc.json.gz"),
        os.path.join(JERC_BASE,"metadata",year,"fatJet_jerc.json.gz"),
        ]

    missing = [path for path in paths if not os.path.isfile(path)]

    if missing:
        formatted = "\n".join(f"  {path}"for path in missing)
        raise FileNotFoundError("The following required files are missing:\n"f"{formatted}")

    return paths


def main(args):
    input_files = collect_input_files(args)
    timestamp = datetime.datetime.now().strftime("%d%b%y_%H%M")
    job_name = f"{args.jobName}_{timestamp}"
    overall_submit_dir = os.path.join(args.submitDirPath, job_name)
    dag_location = os.path.join(overall_submit_dir, "dags")
    dag_inputs_dir = os.path.join(dag_location,"daginputs")
    os.makedirs(dag_inputs_dir, exist_ok=True)
    input_file_text_name = os.path.join(dag_inputs_dir, f"{job_name}_input.txt")

    with open(input_file_text_name, "w", encoding="utf-8") as output_handle:
        output_handle.write("\n".join(input_files))
        output_handle.write("\n")

    helper = os.path.join(JERC_BASE, "run_apply_jerc.py",)

    if not os.path.isfile(helper):
        raise FileNotFoundError(f"Could not find helper executable: {helper}"
        )

    extra_inputs = ",".join(
        get_extra_inputs(args.year)
    )

    command = [
        "farmoutAnalysisJobs",
        "--fwklite",
        "--infer-cmssw-path",
        "--input-files-per-job=1",
        "--job-generates-output-name",
        "--use-singularity=rhel9",
        f"--input-file-list={input_file_text_name}",
        "--assume-input-files-exist",
        "--max-usercode-size=350",
        f"--submit-dir={overall_submit_dir}/submit",
        f"--output-dag-file={dag_location}/dag",
        f"--output-dir={args.destination}/{job_name}",
        "--opsys=rhel9",
        f"--memory-requirements={args.memory}",
        f"--disk-requirements={args.disk}",
        "--input-dir=/",
        f"--extra-inputs={extra_inputs}",
        job_name,
        helper,
        "--",

        # One input file is assigned per farmout job.
        "--input=$inputFileNames",
        "--output-dir=.",
        f"--year={args.year}",
    ]

    if args.isMC:
        command.append("--mc")
    else:
        command.append("--data")

    if args.maxEntries is not None:
        command.append(f"--max-entries={args.maxEntries}"
        )

    if args.keep:
        command.append(f"--keep={args.keep}"
        )

    printable_command = " ".join(shlex.quote(item) for item in command)
    print(f"\nSubmitting farmout job with command:\n {printable_command} \n")
    completed = subprocess.run(printable_command, shell=True, check=False)

    print(
        "farmoutAnalysisJobs exited with code "
        f"{completed.returncode}"
    )

    if completed.returncode != 0:
        sys.exit(completed.returncode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=("Submit NanoAODTools Run-3 JEC/JER jobs ""using farmoutAnalysisJobs."))

    input_group = (parser.add_mutually_exclusive_group(required=True))
    input_group.add_argument("--inputDir", help=("Directory containing input ROOT files."))
    input_group.add_argument("--inputList", help=("Text file containing one input ROOT file ""or XRootD URL per line."))
    parser.add_argument("--destination", required=True, help=("HDFS or local farmout output destination."))
    parser.add_argument("--jobName", required=True, help="Base name for the submission.")
    parser.add_argument("--submitDirPath", default=("/nfs_scratch/"+ os.environ["USER"]+ "/JET_JES_JER_Jobs"),help="Scratch directory for farmout submit files.")
    parser.add_argument("--year", required=True, choices=["2022","2023","2024","2025","2026"], help="Run-3 year.")
    parser.add_argument("--isMC", action="store_true", help=("Process MC. If omitted, the jobs process data."))
    parser.add_argument("--maxEntries", type=int, default=None, help=("Optional number of events processed per input file."))
    parser.add_argument("--keep", default=None, help=("Optional NanoAODTools branch-selection file."))
    parser.add_argument("--memory", type=int, default=3000, help=("Requested worker memory in MB."))
    parser.add_argument("--disk", type=int, default=10000000, help=("Requested worker disk space in kB."))
    parsed_args = parser.parse_args()
    main(parsed_args)