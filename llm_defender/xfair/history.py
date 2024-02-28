import llm_defender.xfair.config as CONFIG
import bittensor as bt
from llm_defender.base.protocol import LLMDefenderProtocol
import time
import json
from string import Template

HISTORY_TEMPLATE = Template(
    'XFAIR_HISTORY"$timestamp","$uuid","$subnet_version","$prompt","$validator_hotkey","$validator_ip","$xfair_model_version","$confidence","$output_json"')


class HistoryLogger:
    def __init__(self):
        if CONFIG.XFairDB is None:
            self.mode = "Log"
        else:
            self.mode = "DB"

    def log(self, synapse: LLMDefenderProtocol):
        if self.mode == "Log":
            log_message = HISTORY_TEMPLATE.substitute(
                timestamp=time.time(),
                uuid=synapse.synapse_uuid,
                subnet_version=synapse.subnet_version,
                prompt=synapse.prompt.replace("\"", "\"\""),
                validator_hotkey=synapse.dendrite.hotkey,
                validator_ip=synapse.dendrite.ip,
                xfair_model_version=CONFIG.XFairModelVersion,
                confidence=synapse.output.get("confidence", "Error"),
                output_json=json.dumps(synapse.output).replace("\"", "\"\"")
            )
            bt.logging.info(log_message)


xfair_history = HistoryLogger()
