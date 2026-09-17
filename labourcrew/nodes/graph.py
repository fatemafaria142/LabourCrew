from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from labourcrew import agents
from labourcrew.llm import get_chat_model
from labourcrew.state import BoardState
from labourcrew.tools import BoardContext

logger = logging.getLogger("labourcrew.graph")


def build_graph(ctx: BoardContext):
    logger.debug("building board graph (chat model=%s)", ctx.settings.openai_chat_model)
    llm = get_chat_model(ctx.settings)

    g = StateGraph(BoardState)

    g.add_node("issue_spotter", agents.make_issue_spotter(llm))
    g.add_node("retrieval_planner", agents.make_retrieval_planner(llm))
    g.add_node("statute_retriever", agents.make_statute_retriever(ctx))
    g.add_node("link_hopper", agents.make_link_hopper(ctx))
    g.add_node("worker_counsel", agents.make_worker_counsel(llm))
    g.add_node("employer_counsel", agents.make_employer_counsel(llm))
    g.add_node("legal_interpreter", agents.make_legal_interpreter(llm))
    g.add_node("trust_auditor", agents.make_trust_auditor(llm))
    g.add_node("supervisor", agents.make_supervisor())
    g.add_node("opinion_writer", agents.make_opinion_writer(llm, ctx.settings))
    g.add_node("citation_checker", agents.make_citation_checker())

    g.add_edge(START, "issue_spotter")
    g.add_edge("issue_spotter", "retrieval_planner")
    g.add_edge("retrieval_planner", "statute_retriever")
    g.add_edge("statute_retriever", "link_hopper")

    # Parallel fan-out: both advocates fire from "link_hopper"; legal_interpreter
    # fans back in once whichever branch(es) ran in this step complete.
    g.add_edge("link_hopper", "worker_counsel")
    g.add_edge("link_hopper", "employer_counsel")
    g.add_edge("worker_counsel", "legal_interpreter")
    g.add_edge("employer_counsel", "legal_interpreter")

    g.add_edge("legal_interpreter", "trust_auditor")
    g.add_edge("trust_auditor", "supervisor")

    g.add_conditional_edges(
        "supervisor",
        agents.route_after_supervisor,
        {
            "worker_counsel": "worker_counsel",
            "employer_counsel": "employer_counsel",
            "retrieval_planner": "retrieval_planner",
            "opinion_writer": "opinion_writer",
        },
    )

    g.add_edge("opinion_writer", "citation_checker")
    g.add_edge("citation_checker", END)

    return g.compile()
