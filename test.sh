## MC

# python3 run_apply_jerc.py   \
#     --input /hdfs/store/user/mithakor/CRAB_skimmed_2024_MC/Hadded/GluGlutoRadiontoHHto2B2Tau_M-1000_narrow_TuneCP5_13p6TeV_madgraph-pythia8.root \
#     --output-dir .  \
#     --year  2024    \
#     --mc    \
#     --max-entries 100   \
#     &> smalltest.log &

## Data
python3 run_apply_jerc.py   \
    --input /hdfs/store/user/mithakor/CRAB_skimmed_2024_data/Hadded/JetMET0_Run2024C-MINIv6NANOv15-v1.root \
    --output-dir .  \
    --year  2024    \
    --data    \
    --max-entries 100   \
    &> smalltest_data.log &

