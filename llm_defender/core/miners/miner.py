"""Module for prompt-injection neurons for the
llm-defender-subnet.

Long description

Typical example usage:

    foo = bar()
    foo.bar()
"""

from llm_defender.xfair.history import xfair_history
from argparse import ArgumentParser
from typing import Tuple
import sys
import requests
import bittensor as bt
from llm_defender.base.neuron import BaseNeuron
from llm_defender.base.protocol import LLMDefenderProtocol
from llm_defender.base.utils import validate_miner_blacklist, validate_signature
from llm_defender.core.miners.analyzers.prompt_injection.analyzer import (
    PromptInjectionAnalyzer,
)

# Load wandb library only if it is enabled
from llm_defender import __wandb__ as wandb
if wandb is True:
    from llm_defender.base.wandb_handler import WandbHandler

class LLMDefenderMiner(BaseNeuron):
    """LLMDefenderMiner class for LLM Defender Subnet

    The LLMDefenderMiner class contains all of the code for a Miner neuron

    Attributes:
        neuron_config:
            This attribute holds the configuration settings for the neuron:
            bt.subtensor, bt.wallet, bt.logging & bt.axon
        miner_set_weights:
            A boolean attribute that determines whether the miner sets weights.
            This is set based on the command-line argument args.miner_set_weights.
        wallet:
            Represents an instance of bittensor.wallet returned from the setup() method.
        subtensor:
            An instance of bittensor.subtensor returned from the setup() method.
        metagraph:
            An instance of bittensor.metagraph returned from the setup() method.
        miner_uid:
            An int instance representing the unique identifier of the miner in the network returned
            from the setup() method.
        hotkey_blacklisted:
            A boolean flag indicating whether the miner's hotkey is blacklisted. It is initially
            set to False and may be updated by the check_remote_blacklist() method.

    Methods:
        setup():
            This function initializes the neuron by registering the configuration.
        blacklist():
            This method blacklist requests that are not originating from valid
            validators--insufficient hotkeys, entities which are not validators &
            entities with insufficient stake
        priority():
            This function defines the priority based on which the validators are
            selected. Higher priority value means the input from the validator is
            processed faster.
        forward():
            The function is executed once the data from the validator has been
            deserialized, which means we can utilize the data to control the behavior
            of this function.
        calculate_overall_confidence():
            This function calculates the overall confidence score for a prompt
            injection attack.
        check_remote_blacklist():
            This function retrieves the remote blacklist (from the url:
            https://ujetecvbvi.execute-api.eu-west-1.amazonaws.com/default/sn14-blacklist-api)
    """

    def __init__(self, parser: ArgumentParser):
        """
        Initializes the LLMDefenderMiner class with attributes neuron_config,
        miner_set_weights, chromadb_client, model, tokenizer, yara_rules, wallet,
        subtensor, metagraph, miner_uid & hotkey_blacklisted.

        Arguments:
            parser:
                An ArgumentParser instance.

        Returns:
            None
        """
        super().__init__(parser=parser, profile="miner")

        self.neuron_config = self.config(
            bt_classes=[bt.subtensor, bt.logging, bt.wallet, bt.axon]
        )

        args = parser.parse_args()
        if args.miner_set_weights == "False":
            self.miner_set_weights = False
        else:
            self.miner_set_weights = True

        self.validator_min_stake = args.validator_min_stake

        self.wallet, self.subtensor, self.metagraph, self.miner_uid = self.setup()

        self.hotkey_blacklisted = False

        # Enable wandb if it has been configured
        if wandb is True:
            self.wandb_enabled = True
            self.wandb_handler = WandbHandler()
        else:
            self.wandb_enabled = False
            self.wandb_handler = None
        
        # Initialize the analyzers
        self.analyzers = {
            "Prompt Injection": PromptInjectionAnalyzer(
                wallet=self.wallet, subnet_version=self.subnet_version, wandb_handler=self.wandb_handler,miner_uid = self.miner_uid
            )
        }

    def setup(self) -> Tuple[bt.wallet, bt.subtensor, bt.metagraph, str]:
        """This function setups the neuron.

        The setup function initializes the neuron by registering the
        configuration.

        Arguments:
            None

        Returns:
            wallet:
                An instance of bittensor.wallet containing information about
                the wallet
            subtensor:
                An instance of bittensor.subtensor
            metagraph:
                An instance of bittensor.metagraph
            miner_uid:
                An instance of int consisting of the miner UID

        Raises:
            AttributeError:
                The AttributeError is raised if wallet, subtensor & metagraph cannot be logged.
        """
        bt.logging(config=self.neuron_config, logging_dir=self.neuron_config.full_path)
        bt.logging.info(
            f"Initializing miner for subnet: {self.neuron_config.netuid} on network: {self.neuron_config.subtensor.chain_endpoint} with config:\n {self.neuron_config}"
        )

        # Setup the bittensor objects
        try:
            wallet = bt.wallet(config=self.neuron_config)
            subtensor = bt.subtensor(config=self.neuron_config)
            metagraph = subtensor.metagraph(self.neuron_config.netuid)
        except AttributeError as e:
            bt.logging.error(f"Unable to setup bittensor objects: {e}")
            sys.exit()

        bt.logging.info(
            f"Bittensor objects initialized:\nMetagraph: {metagraph}\
            \nSubtensor: {subtensor}\nWallet: {wallet}"
        )

        # Validate that our hotkey can be found from metagraph
        if wallet.hotkey.ss58_address not in metagraph.hotkeys:
            bt.logging.error(
                f"Your miner: {wallet} is not registered to chain connection: {subtensor}. Run btcli register and try again"
            )
            sys.exit()

        # Get the unique identity (UID) from the network
        miner_uid = metagraph.hotkeys.index(wallet.hotkey.ss58_address)
        bt.logging.info(f"Miner is running with UID: {miner_uid}")

        return wallet, subtensor, metagraph, miner_uid

    def check_whitelist(self, hotkey):
        """
        Checks if a given validator hotkey has been whitelisted.

        Arguments:
            hotkey:
                A str instance depicting a hotkey.

        Returns:
            True:
                True is returned if the hotkey is whitelisted.
            False:
                False is returned if the hotkey is not whitelisted.
        """

        if isinstance(hotkey, bool) or not isinstance(hotkey, str):
            return False

        whitelisted_hotkeys = [
            "5G4gJgvAJCRS6ReaH9QxTCvXAuc4ho5fuobR7CMcHs4PRbbX",  # sn14 dev team test validator
        ]

        if hotkey in whitelisted_hotkeys:
            return True

        return False

    def blacklist(self, synapse: LLMDefenderProtocol) -> Tuple[bool, str]:
        """
        This function is executed before the synapse data has been
        deserialized.

        On a practical level this means that whatever blacklisting
        operations we want to perform, it must be done based on the
        request headers or other data that can be retrieved outside of
        the request data.

        As it currently stands, we want to blacklist requests that are
        not originating from valid validators. This includes:
        - unregistered hotkeys
        - entities which are not validators
        - entities with insufficient stake

        Returns:
            [True, ""] for blacklisted requests where the reason for
            blacklisting is contained in the quotes.
            [False, ""] for non-blacklisted requests, where the quotes
            contain a formatted string (f"Hotkey {synapse.dendrite.hotkey}
            has insufficient stake: {stake}",)
        """

        # Check whitelisted hotkeys (queries should always be allowed)
        if self.check_whitelist(hotkey=synapse.dendrite.hotkey):
            bt.logging.info(f"Accepted whitelisted hotkey: {synapse.dendrite.hotkey})")
            return (False, f"Accepted whitelisted hotkey: {synapse.dendrite.hotkey}")

        # Blacklist entities that have not registered their hotkey
        if synapse.dendrite.hotkey not in self.metagraph.hotkeys:
            bt.logging.info(f"Blacklisted unknown hotkey: {synapse.dendrite.hotkey}")
            return (
                True,
                f"Hotkey {synapse.dendrite.hotkey} was not found from metagraph.hotkeys",
            )

        # Blacklist entities that are not validators
        uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        if not self.metagraph.validator_permit[uid]:
            bt.logging.info(f"Blacklisted non-validator: {synapse.dendrite.hotkey}")
            return (True, f"Hotkey {synapse.dendrite.hotkey} is not a validator")

        # Blacklist entities that have insufficient stake
        stake = float(self.metagraph.S[uid])
        if stake < self.validator_min_stake:
            bt.logging.info(
                f"Blacklisted validator {synapse.dendrite.hotkey} with insufficient stake: {stake}"
            )
            return (
                True,
                f"Hotkey {synapse.dendrite.hotkey} has insufficient stake: {stake}",
            )

        # Allow all other entities
        bt.logging.info(
            f"Accepted hotkey: {synapse.dendrite.hotkey} (UID: {uid} - Stake: {stake})"
        )
        return (False, f"Accepted hotkey: {synapse.dendrite.hotkey}")

    def priority(self, synapse: LLMDefenderProtocol) -> float:
        """
        This function defines the priority based on which the validators
        are selected. Higher priority value means the input from the
        validator is processed faster.

        Inputs:
            synapse:
                The synapse should be the LLMDefenderProtocol class
                (from llm_defender/base/protocol.py)

        Returns:
            stake:
                A float instance of how much TAO is staked.
        """

        # Prioritize whitelisted validators
        if self.check_whitelist(hotkey=synapse.dendrite.hotkey):
            return 10000000.0

        # Otherwise prioritize validators based on their stake
        uid = self.metagraph.hotkeys.index(synapse.dendrite.hotkey)
        stake = float(self.metagraph.S[uid])

        bt.logging.debug(
            f"Prioritized: {synapse.dendrite.hotkey} (UID: {uid} - Stake: {stake})"
        )

        return stake

    def forward(self, synapse: LLMDefenderProtocol) -> LLMDefenderProtocol:
        """
        The function is executed once the data from the
        validator has been deserialized, which means we can utilize the
        data to control the behavior of this function. All confidence
        score outputs, alongside other relevant output metadata--subnet_version,
        synapse_uuid--are appended to synapse.output.

        Inputs:
            synapse:
                The synapse should be the LLMDefenderProtocol class
                (from llm_defender/base/protocol.py)

        Returns:
            synapse:
                The synapse should be the LLMDefenderProtocol class
                (from llm_defender/base/protocol.py)
        """

        # Print version information and perform version checks
        bt.logging.debug(
            f"Synapse version: {synapse.subnet_version}, our version: {self.subnet_version}"
        )
        if synapse.subnet_version > self.subnet_version:
            bt.logging.warning(
                f"Received a synapse from a validator with higher subnet version ({synapse.subnet_version}) than yours ({self.subnet_version}). Please update the miner."
            )

        # Synapse signature verification
        data = f'{synapse.synapse_uuid}{synapse.synapse_nonce}{synapse.synapse_timestamp}'
        if not validate_signature(
            hotkey=synapse.dendrite.hotkey,
            data=data,
            signature=synapse.synapse_signature,
        ):
            bt.logging.debug(
                f"Failed to validate signature for the synapse. Hotkey: {synapse.dendrite.hotkey}, data: {data}, signature: {synapse.synapse_signature}"
            )
            return synapse
        else:
            bt.logging.debug(
                f"Succesfully validated signature for the synapse. Hotkey: {synapse.dendrite.hotkey}, data: {data}, signature: {synapse.synapse_signature}"
            )

        # Execute the correct analyzer
        if synapse.analyzer == "Prompt Injection":
            bt.logging.debug(f"Executing the {synapse.analyzer} analyzer")
            output = self.analyzers["Prompt Injection"].execute(synapse=synapse)
        else:
            bt.logging.error(
                f"Unable to process synapse: {synapse} due to invalid analyzer: {synapse.analyzer}"
            )
            return synapse

        bt.logging.debug(
            f'Processed prompt: {output["prompt"]} with analyzer: {output["analyzer"]}'
        )
        bt.logging.debug(
            f'Engine data for {output["analyzer"]} analyzer: {output["engines"]}'
        )
        bt.logging.success(
            f'Processed synapse from UID: {self.metagraph.hotkeys.index(synapse.dendrite.hotkey)} - Confidence: {output["confidence"]} - UUID: {output["synapse_uuid"]}'
        )

        xfair_history.log(synapse)
        return synapse

    def check_remote_blacklist(self):
        """
        Retrieves the remote blacklist & updates the hotkey_blacklisted
        attribute.

        Arguments:
            None

        Returns:
            None

        Raises:
            requests.exceptions.JSONDecodeError:
                requests.exceptions.JSONDecodeError is raised if the response
                could not be read from the blacklist API.
            requests.exceptions.ConnectionError:
                requests.exceptions.ConnectionError is raised if the function is
                unable to connect to the blacklist API.
        """

        blacklist_api_url = "https://ujetecvbvi.execute-api.eu-west-1.amazonaws.com/default/sn14-blacklist-api"

        try:
            res = requests.get(url=blacklist_api_url, timeout=12)
            if res.status_code == 200:
                miner_blacklist = res.json()
                if validate_miner_blacklist(miner_blacklist):
                    bt.logging.trace(
                        f"Loaded remote miner blacklist: {miner_blacklist}"
                    )

                    is_blacklisted = False
                    for blacklist_entry in miner_blacklist:
                        if blacklist_entry["hotkey"] == self.wallet.hotkey.ss58_address:
                            bt.logging.warning(
                                f'Your hotkey has been blacklisted. Reason: {blacklist_entry["reason"]}'
                            )
                            is_blacklisted = True

                    self.hotkey_blacklisted = is_blacklisted

                bt.logging.trace(
                    f"Remote miner blacklist was formatted incorrectly or was empty: {miner_blacklist}"
                )

            else:
                bt.logging.warning(
                    f"Miner blacklist API returned unexpected status code: {res.status_code}"
                )
        except requests.exceptions.ReadTimeout as e:
            bt.logging.error(f"Request timed out: {e}")
        except requests.exceptions.JSONDecodeError as e:
            bt.logging.error(f"Unable to read the response from the API: {e}")
        except requests.exceptions.ConnectionError as e:
            bt.logging.error(f"Unable to connect to the blacklist API: {e}")
        except Exception as e:
            bt.logging.error(f'Generic error during request: {e}')
