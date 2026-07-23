#!/usr/bin/env python3
from __future__ import annotations
import argparse
import os
from PhysicsTools.NanoAODTools.postprocessing.framework.postprocessor import PostProcessor
from jerc_config import RUN3_YEARS
from jerc_module import JERCProducer


def parse_args():
    parser = argparse.ArgumentParser(description=("Apply Run-3 AK4/AK8 JEC, MC JER, and Type-1 PuppiMET corrections to NanoAOD."))
    parser.add_argument("-i", "--input", required=True, help=("Input NanoAOD ROOT file or XRootD URL. For data, the filename/path must contain a token such as Run2024G."))
    parser.add_argument("-o", "--output-dir", default=".", help="Directory for the output NanoAOD file.")
    parser.add_argument("-y", "--year", required=True, choices=RUN3_YEARS, help="Run-3 year.")
    data_type_group = (parser.add_mutually_exclusive_group(required=True))
    data_type_group.add_argument("--data", action="store_true", help="Process collision data.")
    data_type_group.add_argument("--mc", action="store_true", help="Process Monte Carlo.")
    parser.add_argument("--max-entries", type=int, default=None, help="Optional maximum number of events to process.")
    return parser.parse_args()


def main():
    
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    jerc_module = JERCProducer(input_file=args.input, year=args.year, is_data=args.data)
    processor = PostProcessor(
        outputDir=args.output_dir,
        inputFiles=[args.input],
        cut=None,
        modules=[jerc_module],
        noOut=False,
        postfix="",
        maxEntries=args.max_entries,
        outputbranchsel="Datadrop.txt",
    )

    processor.run()
if __name__ == "__main__":
    main()