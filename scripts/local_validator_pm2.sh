source .venv/bin/activate
bash scripts/run_neuron.sh \
--name llm-defender-subnet-validator-0 \
--install_only 0 \
--max_memory_restart 5G \
--branch main \
--netuid 1 \
--profile validator \
--wallet.name validator \
--wallet.hotkey default \
--subtensor.chain_endpoint ws://127.0.0.1:9946