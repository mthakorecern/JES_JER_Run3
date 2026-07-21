python3 submit_jobs.py \
    --inputList /afs/hep.wisc.edu/home/mithakor/HH_bb_tautau_Analysis/JEC_JER/CMSSW_15_0_5/src/JEC_JER/MC_JME.txt \
    --destination /hdfs/store/user/mithakor/JERC_2024_MC \
    --jobName JET_JEC_JER_Processed \
    --submitDirPath /nfs_scratch/mithakor/JET_JES_JER_Jobs/MC   \
    --year 2024 \
    --isMC  \
    &> MC.log &