"""langchain-keeperhub — LangChain toolkit for reliable Web3 execution via KeeperHub."""

import logging as _logging

# Standard library-logging contract: attach a NullHandler so the package never
# emits "no handlers could be found" warnings and so the consumer fully controls
# log destination/levels (see python.org logging HOWTO).
_logging.getLogger(__name__).addHandler(_logging.NullHandler())

from langchain_keeperhub.client import KeeperHubClient
from langchain_keeperhub.ens import ENSClient
from langchain_keeperhub.ens_chains import (
    ENSChainProfile,
    list_ens_chain_profiles,
    resolve_ens_chain,
    reverse_primary_name,
)
from langchain_keeperhub.history import (
    ExecutionKind,
    ExecutionRecord,
    ExecutionStore,
    SqliteExecutionStore,
)
from langchain_keeperhub.toolkit import KeeperHubToolkit
from langchain_keeperhub.tools import (
    CheckAndExecuteTool,
    ContractCallTool,
    FetchContractABITool,
    GetExecutionStatusTool,
    GetWalletAddressTool,
    ListChainsTool,
    ListExecutionsTool,
    ResolveENSTool,
    ReverseResolveENSTool,
    TransferFundsTool,
)

__all__ = [
    "ENSChainProfile",
    "ENSClient",
    "KeeperHubClient",
    "KeeperHubToolkit",
    "CheckAndExecuteTool",
    "ContractCallTool",
    "FetchContractABITool",
    "GetExecutionStatusTool",
    "GetWalletAddressTool",
    "ListChainsTool",
    "ListExecutionsTool",
    "ResolveENSTool",
    "ReverseResolveENSTool",
    "TransferFundsTool",
    "ExecutionKind",
    "ExecutionRecord",
    "ExecutionStore",
    "SqliteExecutionStore",
    "list_ens_chain_profiles",
    "resolve_ens_chain",
    "reverse_primary_name",
]
