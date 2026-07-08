#!/usr/bin/env python3
"""
HandoffRail — Basic Handoff Example

A simple two-agent handoff: SalesBot creates a packet, BillingBot claims it.

Prerequisites:
    pip install handoffrail-sdk
    # Start the server: uvicorn app.main:app --reload --port 8080
    # Create an API key:
    # curl -X POST http://localhost:8080/api/v1/keys \
    #   -H "Content-Type: application/json" -d '{"name":"demo"}'

Usage:
    python basic_handoff.py
"""

from handoffrail.sdk import HandoffRailClient
from handoffrail.sdk.models import (
    Actions,
    AgentInfo,
    ContextEntry,
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

    print("🚄 HandoffRail — Basic Handoff Example\n")
    print("=" * 60)

    # ── Step 1: SalesBot creates a handoff packet ──────────────────────
    print("\n📦 Step 1: SalesBot creates a handoff packet\n")

    packet_create = PacketCreate(
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
            tags=["upgrade", "business-tier"],
        ),
        context=PacketContext(
            summary="Customer wants to upgrade from Pro to Business tier. Eligibility confirmed.",
            conversation_state=[
                ContextEntry(
                    role="user",
                    content="I'd like to upgrade to the Business plan please.",
                ),
                ContextEntry(
                    role="agent",
                    content="Great news — your account is eligible! Let me hand you to our billing team.",
                ),
            ],
        ),
        decisions=[],
        actions=Actions(
            pending=[
                PendingAction(
                    id="a1",
                    description="Process Business tier upgrade payment",
                    assignee="billing-01",
                    priority="high",
                    depends_on=[],
                ),
            ],
            completed=[],
            failed=[],
        ),
        dependencies=[],
        hitl=None,
    )

    packet = client.create_packet(packet_create)

    print(f"  Packet ID:    {packet.id}")
    print(f"  Status:       {packet.status}")
    print(f"  Source:       {packet.metadata.source_agent.name}")
    print(f"  Target:       {packet.metadata.target_agent.name}")
    print(f"  Summary:      {packet.context.summary}")
    print(f"  Priority:     {packet.metadata.priority}")
    print(f"  Tags:         {', '.join(packet.metadata.tags)}")

    # ── Step 2: BillingBot claims the packet ───────────────────────────
    print("\n\n📥 Step 2: BillingBot claims the packet\n")

    claimed = client.claim_packet(
        packet.id,
        agent_id="billing-01",
        agent_name="BillingBot",
        framework="crewai",
    )

    print(f"  Packet ID:    {claimed.id}")
    print(f"  Status:       {claimed.status}")
    print(f"  Claimed at:   {claimed.metadata.claimed_at}")

    # ── Step 3: BillingBot processes the action ─────────────────────────
    print("\n\n⚙️  Step 3: BillingBot processes the upgrade\n")

    # Update status to in_progress
    from handoffrail.sdk.models import PacketUpdate

    in_progress = client.update_packet(
        packet.id,
        PacketUpdate(status="in_progress"),
    )

    print(f"  Status:       {in_progress.status}")

    # ── Step 4: BillingBot completes the handoff ────────────────────────
    print("\n\n✅ Step 4: BillingBot completes the handoff\n")

    completed = client.complete_packet(packet.id)

    print(f"  Packet ID:    {completed.id}")
    print(f"  Status:       {completed.status}")
    print(f"  Completed at: {completed.metadata.completed_at}")

    # ── Step 5: View the audit trail ────────────────────────────────────
    print("\n\n📋 Step 5: View the audit trail\n")

    history = client.get_history(packet.id)
    for event in history.events:
        print(f"  {event.timestamp}  {event.event_type:20s}  by {event.actor}")

    # ── Summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("🎉 Basic handoff complete!")
    print(f"   SalesBot → BillingBot: '{packet.context.summary}'")
    print("   Full lifecycle: created → claimed → in_progress → completed")
    print("=" * 60)

    client.close()


if __name__ == "__main__":
    main()
