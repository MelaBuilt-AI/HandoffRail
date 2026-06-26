# HandoffRail — Research Notes

## Product Overview
**Category:** Custom AI Agents & Business Integration  
**Tagline:** Session-continuity middleware for multi-agent workflows

### Problem
When one AI agent hands work to another (or to a human), context gets lost. Decisions, pending actions, dependencies — all vanish at the handoff point. Companies stacking 3–5 specialized agents hit this wall hard.

### Solution
HandoffRail captures full context into structured "handoff packets":
- Conversation state
- Decisions made
- Pending actions
- Dependencies
- Human-in-the-loop checkpoints

Receiving agent or person picks up exactly where things left off. Zero context loss.

## Competitive Landscape

| Product | Focus | Gap |
|---------|-------|-----|
| AgentOps | Agent governance & cost tracking | No inter-agent continuity |
| Fluq | Agent lifecycle management | Monitoring, not handoff |
| Prufer | Compliance & governance | Not operational continuity |
| Agentman | Agent building/testing platform | Lifecycle, not handoff packets |

**Key differentiator:** Nobody does structured agent-to-agent handoff packets with human-in-the-loop checkpoints. This is a genuine gap.

## Target Audience
- Teams running multi-agent setups (sales → support → billing agent)
- Solo operators with long workflows spanning human checkpoints
- Companies with 3–5+ specialized agents losing thread continuity

## Revenue Model
- **Free:** 5 handoffs/day, 2 agents
- **Pro $29/mo:** Unlimited handoffs, 10 agents
- **Business $99/mo:** API access, audit trails, SSO

## Build Timeline
6–8 weeks to MVP

## Why Now
- Agentic AI adoption exploding
- Everyone building individual agents, nobody solving the continuity problem
- As agent stacks grow, handoff quality becomes the bottleneck
- First-mover advantage in a category that will only grow

## Technical Considerations (Initial)
- Core primitive: the "handoff packet" — structured JSON with context, decisions, actions, dependencies
- Needs: API-first design, real-time handoff streaming, versioning of packets
- Integration points: LangChain, CrewAI, AutoGen, OpenAI Assistants API, custom agents
- Storage: packet history with search/filter
- Security: encryption at rest, audit trail, access control

## Next Steps
- [ ] Define handoff packet schema v1
- [ ] Core API design (create packet, receive packet, query history)
- [ ] SDK for agent frameworks (LangChain, CrewAI first)
- [ ] MVP scope definition
- [ ] Landing page