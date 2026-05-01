"""TCS Agentic AI Platform — HITL Context Framework."""

from .lineage import InMemoryLineageRecorder, make_event
from .llm import (
    AzureOpenAIClient,
    FakeLLMClient,
    LLMClient,
    OpenAIClient,
    build_llm_client_from_env,
)
from .models import (
    AgentAction,
    KnowledgeContext,
    KnowledgeFact,
    KnowledgeQuery,
    KnowledgeRef,
    LineageEvent,
    ReviewDecision,
    ReviewDecisionKind,
    ReviewTicket,
    Stage,
    StageContext,
    TransportMode,
    TruthSourceMode,
)
from .protocols import (
    AgentIntakeBinder,
    HITLTransport,
    KnowledgeResolver,
    KnowledgeResolverRegistry,
    LineageRecorder,
    ProposalBinder,
    ReviewBinder,
    ReviewerSurface,
)
from .service import HITLContextService
from .surface_teams import TeamsAdaptiveCardSurface
from .transport import (
    AsyncQueueTransport,
    DecisionStore,
    OutboundQueue,
    SyncInProcessTransport,
)

__version__ = "0.1.0"

__all__ = [
    # models
    "AgentAction", "KnowledgeContext", "KnowledgeFact", "KnowledgeQuery",
    "KnowledgeRef", "LineageEvent", "ReviewDecision", "ReviewDecisionKind",
    "ReviewTicket", "Stage", "StageContext", "TransportMode", "TruthSourceMode",
    # protocols
    "AgentIntakeBinder", "HITLTransport", "KnowledgeResolver",
    "KnowledgeResolverRegistry", "LineageRecorder", "ProposalBinder",
    "ReviewBinder", "ReviewerSurface",
    # impls
    "HITLContextService", "InMemoryLineageRecorder", "TeamsAdaptiveCardSurface",
    "SyncInProcessTransport", "AsyncQueueTransport",
    "OutboundQueue", "DecisionStore",
    # helpers
    "make_event",
    # llm adapter
    "LLMClient", "OpenAIClient", "AzureOpenAIClient", "FakeLLMClient",
    "build_llm_client_from_env",
]
