source .venv/bin/activate
bash scripts/run_neuron.sh \
--name llm-defender-subnet-miner-0 \
--install_only 0 \
--max_memory_restart 10G \
--branch main \
--netuid 1 \
--profile miner \
--wallet.name miner \
--wallet.hotkey default \
--axon.port 15000 \
--miner_set_weights True \
--subtensor.chain_endpoint ws://127.0.0.1:9946 \
--validator_min_stake 0