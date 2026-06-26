#!/usr/bin/env python3
"""
HandoffRail — Chain Handoff Example with HITL Approval

A multi-agent chain: SalesBot → (HITL approval) → BillingBot → OnboardBot

This demonstrates:
1. Creating a handoff with a Human-in-the-Loop checkpoint
2. Responding to the HITL checkpoint
3. Chaining handoffs between multiple agents

Prerequisites:
    pip install handoffrail-sdk
    # Start the server: uvicorn app.main:app --reload --port 8080
    # Create an API key: curl -X POST http://localhost:8080/api/v1/keys -H "Content-Type: application/json" -d '{"name":"demo"}'

Usage:
    python chain_handoff.py
"""

from handoffrail.sdk import HandoffRailClient
from handoffrail.sdk.models import (
    Actions,
    AgentInfo,
    ChainHandoffRequest,
    ContextEntry,
    HitlCheckpoint,
    Metadata,
    PacketContext,
    PacketCreate,
    PendingAction,
    TargetAgentInfo,
)

# ──────────────────────────────────────────────────────────────────────
# Configuration — update these for your setup
# ──────────────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8080/api/v1"
API_KEY = "hr_your_key_here"  # Replace with your API key


def main():
    # ── Connect ────────────────────────────────────────────────────────
    client = HandoffRailClient(base_url=BASE_URL, api_key=API_KEY)

    print("🚄 HandoffRail — Chain Handoff + HITL Example\n")
    print("=" * 60)

    # ════════════════════════════════════════════════════════════════════
    # PHASE 1: SalesBot creates a handoff with HITL checkpoint
    # ════════════════════════════════════════════════════════════════════

    print("\n📦 Phase 1: SalesBot creates a handoff requiring human approval\n")

    packet = client.create_packet(PacketCreate(
        metadata=Metadata(
            source_agent=AgentInfo(
                id="sales-01",
                name="SalesBot",
                framework="langchain",
            ),
            target_agent=TargetAgentInfo(
                id="billing-01",
                name="BillingBot",
            ),
            priority="high",
            tags=["enterprise-upgrade", "hitl-required"],
        ),
        context=PacketContext(
            summary=(
                "Customer requesting Enterprise tier upgrade ($2,400/yr). "
                "Account has 42-day-old order with $500 pending refund. "
                "Requires manager approval before processing."
            ),
            conversation_state=[
                ContextEntry(
                    role="user",
                    content="We'd like to upgrade 50 seats to Enterprise tier.",
                ),
                ContextEntry(
                    role="agent",
                    content="That's a significant upgrade. I'll need manager approval for the pricing and the pending refund situation. Let me escalate this.",
                ),
            ],
        ),
        decisions=[],
        actions=Actions(
            pending=[
                PendingAction(
                    id="a1",
                    description="Approve Enterprise tier pricing for 50 seats",
                    assignee="human",
                    priority="critical",
                    depends_on=[],
                ),
                PendingAction(
                    id="a2",
                    description="Process $500 refund for order #1234",
                    assignee="billing-01",
                    priority="high",
                    depends_on=["a1"],
                ),
                PendingAction(
                    id="a3",
                    description="Process Enterprise upgrade payment ($2,400/yr)",
                    assignee="billing-01",
                    priority="high",
                    depends_on=["a1"],
                ),
            ],
            completed=[],
            failed=[],
        ),
        dependencies=[],
        hitl=HitlCheckpoint(
            required=True,
            reason="Enterprise tier upgrade ($2,400/yr) with pending refund requires manager approval",
            question="Should we approve the Enterprise upgrade and process the $500 refund for order #1234?",
            options=[
                "Approve upgrade + full refund",
                "Approve upgrade + partial refund",
                "Approve upgrade only (deny refund)",
                "Deny both",
            ],
            timeout_seconds=86400,  # 24 hours
        ),
    ))

    print(f"  Packet ID:    {packet.id}")
    print(f"  Status:       {packet.status}")  # "awaiting_human"
    print(f"  HITL:         {packet.hitl.reason}")
    print(f"  Options:      {', '.join(packet.hitl.options or [])}")

    # ════════════════════════════════════════════════════════════════════
    # PHASE 2: Human manager responds to HITL checkpoint
    # ════════════════════════════════════════════════════════════════════

    print("\n\n🧑‍⚖️  Phase 2: Manager reviews and approves\n")

    # In production, this would be a separate process — a web dashboard,
    # Slack notification, or CLI command. Here we simulate it directly.
    responded = client.respond_to_hitl(
        packet.id,
        response="Approve upgrade + full refund",
        responded_by="sarah@company.com",
        notes="Long-standing customer, 3-year account. Both approved.",
    )

    print(f"  Response:     {responded.hitl.response}")
    print(f"  Responded by: {responded.hitl.responded_by}")
    print(f"  Status:       {responded.status}")  # "claimed" or "in_progress"

    # ════════════════════════════════════════════════════════════════════
    # PHASE 3: BillingBot claims and processes
    # ════════════════════════════════════════════════════════════════════

    print("\n\n💰 Phase 3: BillingBot processes the approved handoff\n")

    # BillingBot picks up the packet (may already be claimed from HITL response)
    if responded.status == "claimed":
        from handoffrail.sdk.models import PacketUpdate
        in_progress = client.update_packet(
            packet.id,
            PacketUpdate(status="in_progress"),
        )
        print(f"  Status:       {in_progress.status}")
    else:
        print(f"  Status:       {responded.status} (already in progress)")

    # BillingBot completes its work
    completed = client.complete_packet(packet.id)

    print(f"  Packet ID:    {completed.id}")
    print(f"  Status:       {completed.status}")
    print(f"  Completed at: {completed.metadata.completed_at}")

    # ════════════════════════════════════════════════════════════════════
    # PHASE 4: Chain handoff — BillingBot hands off to OnboardBot
    # ════════════════════════════════════════════════════════════════════

    print("\n\n🔗 Phase 4: Chain handoff — BillingBot → OnboardBot\n")

    chained = client.chain_handoff(
        packet.id,
        ChainHandoffRequest(
            metadata=Metadata(
                source_agent=AgentInfo(
                    id="billing-01",
                    name="BillingBot",
                    framework="crewai",
                ),
                target_agent=TargetAgentInfo(
                    id="onboard-01",
                    name="OnboardBot",
                ),
                priority="normal",
                tags=["enterprise-upgrade", "onboarding"],
            ),
            context=PacketContext(
                summary=(
                    "Enterprise upgrade and refund both processed. "
                    "Customer needs onboarding: 50 Enterprise seats, "
                    "priority support setup, and dedicated CSM assignment."
                ),
                conversation_state=[
                    ContextEntry(
                        role="agent",
                        content="Payment processed. Enterprise tier active for 50 seats. Refund of $500 issued to original payment method.",
                    ),
                ],
            ),
            actions=Actions(
                pending=[
                    PendingAction(
                        id="c1",
                        description="Set up Enterprise workspace for 50 seats",
                        assignee="onboard-01",
                        priority="normal",
                        depends_on=[],
                    ),
                    PendingAction(
                        id="c2",
                        description="Assign dedicated Customer Success Manager",
                        assignee="onboard-01",
                        priority="normal",
                        depends_on=[],
                    ),
                    PendingAction(
                        id="c3",
                        description="Schedule priority support onboarding call",
                        assignee="onboard-01",
                        priority="low",
                        depends_on=["c1"],
                    ),
                ],
                completed=[],
                failed=[],
            ),
        ),
    )

    print(f"  Chain Packet:  {chained.id}")
    print(f"  Parent:        {chained.parent_packet_id}")
    print(f"  Status:        {chained.status}")
    print(f"  Source:        {chained.metadata.source_agent.name}")
    print(f"  Target:        {chained.metadata.target_agent.name}")
    print(f"  Summary:       {chained.context.summary}")

    # ════════════════════════════════════════════════════════════════════
    # PHASE 5: OnboardBot claims the chain
    # ════════════════════════════════════════════════════════════════════

    print("\n\n🚀 Phase 5: OnboardBot claims the chained packet\n")

    onboard_claimed = client.claim_packet(
        chained.id,
        agent_id="onboard-01",
        agent_name="OnboardBot",
    )

    print(f"  Status:       {onboard_claimed.status}")

    # OnboardBot completes onboarding
    onboard_completed = client.complete_packet(chained.id)

    print(f"  Final status: {onboard_completed.status}")

    # ════════════════════════════════════════════════════════════════════
    # PHASE 6: View the full audit trail
    # ════════════════════════════════════════════════════════════════════

    print("\n\n📋 Phase 6: Full audit trail for original packet\n")

    history = client.get_history(packet.id)
    for event in history.events:
        details = f" ({event.details})" if event.details else ""
        print(f"  {event.timestamp}  {event.event_type:20s}  by {event.actor}{details}")

    print("\n\n📋 Audit trail for chained packet\n")

    chain_history = client.get_history(chained.id)
    for event in chain_history.events:
        details = f" ({event.details})" if event.details else ""
        print(f"  {event.timestamp}  {event.event_type:20s}  by {event.actor}{details}")

    # ── Summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("🎉 Chain handoff with HITL complete!")
    print()
    print("  Chain flow:")
    print("  SalesBot → [HITL: Manager approves] → BillingBot → OnboardBot")
    print()
    print(f"  Original packet: {packet.id}")
    print(f"  Chain packet:    {chained.id}")
    print(f"  HITL response:   {responded.hitl.response}")
    print(f"  Approved by:     {responded.hitl.responded_by}")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
