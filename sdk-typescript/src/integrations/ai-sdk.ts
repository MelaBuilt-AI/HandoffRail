/**
 * HandoffRail integration for the Vercel AI SDK.
 *
 * Provides:
 * - {@link HandoffRailToolSet} — A tool bundle that exposes HandoffRail
 *   operations as Vercel AI SDK `tool` definitions.
 * - {@link createHandoffRailTools} — A convenience factory that returns
 *   tool definitions suitable for use with `maxSteps` or agentic loops.
 *
 * Requires the `ai` package as an optional dependency:
 * ```
 * npm install ai
 * ```
 *
 * @module
 */

import type {
  PacketCreate,
  PacketUpdate,
  ChainHandoffRequest,
  PacketContext,
  Metadata,
  AgentInfo,
  TargetAgentInfo,
  ListPacketsOptions,
} from '../models';

import {
  HandoffRailClient,
} from '../client';

import { HandoffRailError } from '../errors';

// ── Type helpers ─────────────────────────────────────────────────────────

/**
 * Minimal tool definition shape compatible with the Vercel AI SDK `tool()`
 * helper from `ai` package v3+.
 *
 * The actual `ai` package exports a `tool()` function:
 * ```typescript
 * import { tool } from 'ai';
 * ```
 *
 * This integration works with both v3 and v4 of the `ai` package.
 */
export interface AIToolDefinition {
  description: string;
  parameters: Record<string, unknown>;
  execute?: (args: Record<string, unknown>) => Promise<unknown>;
}

// ── HandoffRail Tool Set ─────────────────────────────────────────────────

/**
 * A bundle of HandoffRail operations exposed as Vercel AI SDK tools.
 *
 * Each tool method returns a tool definition compatible with the `ai` SDK.
 *
 * Usage with `ai` v3+:
 * ```typescript
 * import { generateText, tool } from 'ai';
 * import { HandoffRailClient } from 'handoffrail-sdk';
 * import { createHandoffRailTools } from 'handoffrail-sdk/integrations/ai-sdk';
 *
 * const client = new HandoffRailClient({ baseUrl: '...', apiKey: '...' });
 * const handoffTools = createHandoffRailTools(client, {
 *   agentId: 'sales-01',
 *   agentName: 'SalesBot',
 * });
 *
 * const result = await generateText({
 *   model: yourModel,
 *   tools: handoffTools,
 *   maxSteps: 10,
 * });
 * ```
 */
export class HandoffRailToolSet {
  private readonly client: HandoffRailClient;
  private readonly agentId: string;
  private readonly agentName: string;
  private readonly framework?: string;

  constructor(
    client: HandoffRailClient,
    options: { agentId: string; agentName: string; framework?: string },
  ) {
    this.client = client;
    this.agentId = options.agentId;
    this.agentName = options.agentName;
    this.framework = options.framework;
  }

  /**
   * Create a handoff packet and return a tool definition for it.
   *
   * The tool accepts target agent info, summary, priority, tags, and an
   * optional HITL reason. It constructs a complete {@link PacketCreate}
   * payload using the configured source agent identity.
   */
  createPacket(): AIToolDefinition {
    return {
      description:
        'Create a new handoff handoff packet to transfer context to another agent. ' +
        'Use this when the current agent has completed its work and needs to hand off ' +
        'to another agent or when human-in-the-loop approval is needed.',
      parameters: {
        type: 'object',
        properties: {
          target_agent_id: {
            type: 'string',
            description: 'ID of the agent to receive the handoff.',
          },
          target_agent_name: {
            type: 'string',
            description: 'Human-readable name of the target agent.',
          },
          summary: {
            type: 'string',
            description: 'Natural-language summary of the work done so far.',
          },
          priority: {
            type: 'string',
            enum: ['low', 'normal', 'high', 'critical'],
            description: 'Packet priority (default: normal).',
          },
          tags: {
            type: 'string',
            description: 'Comma-separated tags for filtering.',
          },
          hitl_reason: {
            type: 'string',
            description:
              'If provided, creates a human-in-the-loop checkpoint with this reason.',
          },
          hitl_question: {
            type: 'string',
            description: 'Question to ask the human reviewer (requires hitl_reason).',
          },
        },
        required: ['target_agent_id', 'target_agent_name', 'summary'],
      },
      execute: async (args: Record<string, unknown>) => {
        const targetAgentId = args.target_agent_id as string;
        const targetAgentName = args.target_agent_name as string;
        const summary = args.summary as string;
        const priority = (args.priority as string) ?? 'normal';
        const tagsStr = args.tags as string | undefined;
        const hitlReason = args.hitl_reason as string | undefined;
        const hitlQuestion = args.hitl_question as string | undefined;

        const sourceAgent: AgentInfo = {
          id: this.agentId,
          name: this.agentName,
          framework: this.framework,
        };
        const targetAgent: TargetAgentInfo = {
          id: targetAgentId,
          name: targetAgentName,
        };
        const metadata: Metadata = {
          source_agent: sourceAgent,
          target_agent: targetAgent,
          priority: priority as 'low' | 'normal' | 'high' | 'critical',
          tags: tagsStr ? tagsStr.split(',').map((t) => t.trim()) : undefined,
        };
        const context: PacketContext = {
          summary,
        };

        const packet: PacketCreate = {
          metadata,
          context,
          hitl: hitlReason
            ? {
                required: true,
                reason: hitlReason,
                question: hitlQuestion,
              }
            : undefined,
        };

        try {
          const result = this.client.createPacket(packet);
          return {
            status: 'created',
            packet_id: result.id,
            summary: result.context.summary,
            priority: result.metadata.priority,
          };
        } catch (error) {
          if (error instanceof HandoffRailError) {
            return { error: error.message, error_type: error.name };
          }
          throw error;
        }
      },
    };
  }

  /**
   * Claim an available handoff packet.
   */
  claimPacket(): AIToolDefinition {
    return {
      description:
        'Claim an available handoff packet for processing. ' +
        'This assigns the packet to the current agent and changes its status to "claimed".',
      parameters: {
        type: 'object',
        properties: {
          packet_id: {
            type: 'string',
            description: 'The UUID of the packet to claim.',
          },
        },
        required: ['packet_id'],
      },
      execute: async (args: Record<string, unknown>) => {
        const packetId = args.packet_id as string;

        try {
          const result = this.client.claimPacket(packetId, {
            agent_id: this.agentId,
            agent_name: this.agentName,
            framework: this.framework,
          });
          return {
            status: 'claimed',
            packet_id: result.id,
            summary: result.context.summary,
          };
        } catch (error) {
          if (error instanceof HandoffRailError) {
            return { error: error.message, error_type: error.name };
          }
          throw error;
        }
      },
    };
  }

  /**
   * Update a handoff packet with progress or new information.
   */
  updatePacket(): AIToolDefinition {
    return {
      description:
        'Update an existing handoff packet with status changes, new decisions, ' +
        'pending actions, or an updated summary.',
      parameters: {
        type: 'object',
        properties: {
          packet_id: {
            type: 'string',
            description: 'The UUID of the packet to update.',
          },
          status: {
            type: 'string',
            enum: ['created', 'claimed', 'in_progress', 'awaiting_human', 'completed', 'failed'],
            description: 'New status for the packet.',
          },
          summary: {
            type: 'string',
            description: 'Updated context summary.',
          },
        },
        required: ['packet_id'],
      },
      execute: async (args: Record<string, unknown>) => {
        const packetId = args.packet_id as string;
        const update: PacketUpdate = {};

        if (args.status) {
          update.status = args.status as PacketUpdate['status'];
        }
        if (args.summary) {
          update.context = {
            summary: args.summary as string,
          };
        }

        try {
          const result = this.client.updatePacket(packetId, update);
          return {
            status: 'updated',
            packet_id: result.id,
            packet_status: result.status,
          };
        } catch (error) {
          if (error instanceof HandoffRailError) {
            return { error: error.message, error_type: error.name };
          }
          throw error;
        }
      },
    };
  }

  /**
   * Mark a handoff packet as completed.
   */
  completePacket(): AIToolDefinition {
    return {
      description:
        'Mark a handoff packet as completed. ' +
        'Use this when the current agent has finished processing the handoff.',
      parameters: {
        type: 'object',
        properties: {
          packet_id: {
            type: 'string',
            description: 'The UUID of the packet to complete.',
          },
        },
        required: ['packet_id'],
      },
      execute: async (args: Record<string, unknown>) => {
        const packetId = args.packet_id as string;

        try {
          const result = this.client.completePacket(packetId);
          return {
            status: 'completed',
            packet_id: result.id,
          };
        } catch (error) {
          if (error instanceof HandoffRailError) {
            return { error: error.message, error_type: error.name };
          }
          throw error;
        }
      },
    };
  }

  /**
   * List available handoff packets matching criteria.
   */
  listPackets(): AIToolDefinition {
    return {
      description:
        'List handoff packets with optional filters. ' +
        'Use this to discover available handoffs, check packet status, ' +
        'or find packets awaiting human review.',
      parameters: {
        type: 'object',
        properties: {
          status: {
            type: 'string',
            description:
              'Comma-separated status filter (e.g. "created,claimed").',
          },
          target_agent: {
            type: 'string',
            description: 'Filter by target agent ID.',
          },
          source_agent: {
            type: 'string',
            description: 'Filter by source agent ID.',
          },
          limit: {
            type: 'number',
            description: 'Max results (default 50).',
          },
        },
      },
      execute: async (args: Record<string, unknown>) => {
        const options: ListPacketsOptions = {};

        if (args.status) options.status = args.status as string;
        if (args.target_agent) options.target_agent = args.target_agent as string;
        if (args.source_agent) options.source_agent = args.source_agent as string;
        if (args.limit) options.limit = args.limit as number;

        try {
          const result = this.client.listPackets(options);
          return {
            total: result.total,
            packets: result.packets.map((p) => ({
              id: p.id,
              status: p.status,
              summary: p.context.summary,
              source_agent: p.metadata.source_agent.name,
              target_agent: p.metadata.target_agent.name,
              priority: p.metadata.priority,
              created_at: p.created_at,
            })),
          };
        } catch (error) {
          if (error instanceof HandoffRailError) {
            return { error: error.message, error_type: error.name };
          }
          throw error;
        }
      },
    };
  }

  /**
   * Get a handoff packet by ID.
   */
  getPacket(): AIToolDefinition {
    return {
      description:
        'Get the full details of a handoff packet by its ID. ' +
        'Returns the complete packet including context, decisions, actions, and dependencies.',
      parameters: {
        type: 'object',
        properties: {
          packet_id: {
            type: 'string',
            description: 'The UUID of the packet to retrieve.',
          },
        },
        required: ['packet_id'],
      },
      execute: async (args: Record<string, unknown>) => {
        const packetId = args.packet_id as string;

        try {
          const result = this.client.getPacket(packetId);
          return {
            id: result.id,
            status: result.status,
            summary: result.context.summary,
            metadata: result.metadata,
            decisions: result.decisions,
            actions: result.actions,
            dependencies: result.dependencies,
            hitl: result.hitl,
            created_at: result.created_at,
            updated_at: result.updated_at,
          };
        } catch (error) {
          if (error instanceof HandoffRailError) {
            return { error: error.message, error_type: error.name };
          }
          throw error;
        }
      },
    };
  }

  /**
   * Respond to a human-in-the-loop checkpoint.
   */
  respondToHitl(): AIToolDefinition {
    return {
      description:
        'Submit a human response to a HITL (human-in-the-loop) checkpoint. ' +
        'Use this when a human has reviewed a packet that was awaiting human input.',
      parameters: {
        type: 'object',
        properties: {
          packet_id: {
            type: 'string',
            description: 'The UUID of the packet with the HITL checkpoint.',
          },
          response: {
            type: 'string',
            description: "The human's response text.",
          },
          notes: {
            type: 'string',
            description: 'Optional additional notes.',
          },
        },
        required: ['packet_id', 'response'],
      },
      execute: async (args: Record<string, unknown>) => {
        const packetId = args.packet_id as string;
        const response = args.response as string;

        try {
          const result = this.client.respondToHitl(packetId, {
            response,
            responded_by: this.agentId,
            notes: args.notes as string | undefined,
          });
          return {
            status: 'responded',
            packet_id: result.id,
            packet_status: result.status,
          };
        } catch (error) {
          if (error instanceof HandoffRailError) {
            return { error: error.message, error_type: error.name };
          }
          throw error;
        }
      },
    };
  }

  /**
   * Get the event history for a packet.
   */
  getPacketHistory(): AIToolDefinition {
    return {
      description:
        'Get the event history / audit trail for a handoff packet. ' +
        'Returns all events that have occurred on the packet.',
      parameters: {
        type: 'object',
        properties: {
          packet_id: {
            type: 'string',
            description: 'The UUID of the packet.',
          },
        },
        required: ['packet_id'],
      },
      execute: async (args: Record<string, unknown>) => {
        const packetId = args.packet_id as string;

        try {
          const result = this.client.getPacketHistory(packetId);
          return {
            packet_id: result.packet_id,
            events: result.events,
          };
        } catch (error) {
          if (error instanceof HandoffRailError) {
            return { error: error.message, error_type: error.name };
          }
          throw error;
        }
      },
    };
  }

  /**
   * Create a chained follow-up packet from an existing packet.
   */
  chainPacket(): AIToolDefinition {
    return {
      description:
        'Create a chained follow-up handoff packet from an existing packet. ' +
        'Use this when processing continues beyond the initial handoff and needs ' +
        'to be passed to another agent.',
      parameters: {
        type: 'object',
        properties: {
          parent_packet_id: {
            type: 'string',
            description: 'The UUID of the parent packet to chain from.',
          },
          target_agent_id: {
            type: 'string',
            description: 'ID of the next agent to receive the handoff.',
          },
          target_agent_name: {
            type: 'string',
            description: 'Name of the next agent.',
          },
          summary: {
            type: 'string',
            description: 'Summary for the follow-up packet.',
          },
        },
        required: ['parent_packet_id', 'target_agent_id', 'target_agent_name', 'summary'],
      },
      execute: async (args: Record<string, unknown>) => {
        const parentPacketId = args.parent_packet_id as string;
        const targetAgentId = args.target_agent_id as string;
        const targetAgentName = args.target_agent_name as string;
        const summary = args.summary as string;

        const sourceAgent: AgentInfo = {
          id: this.agentId,
          name: this.agentName,
          framework: this.framework,
        };
        const targetAgent: TargetAgentInfo = {
          id: targetAgentId,
          name: targetAgentName,
        };

        const request: ChainHandoffRequest = {
          metadata: {
            source_agent: sourceAgent,
            target_agent: targetAgent,
          },
          context: {
            summary,
          },
        };

        try {
          const result = this.client.chainPacket(parentPacketId, request);
          return {
            status: 'chained',
            packet_id: result.id,
            parent_packet_id: parentPacketId,
          };
        } catch (error) {
          if (error instanceof HandoffRailError) {
            return { error: error.message, error_type: error.name };
          }
          throw error;
        }
      },
    };
  }

  /**
   * Get all tool definitions as a record keyed by tool name.
   *
   * The returned record is suitable for spreading into the `tools` option
   * of `generateText`, `streamText`, or similar AI SDK functions.
   *
   * @example
   * ```typescript
   * const toolSet = new HandoffRailToolSet(client, {
   *   agentId: 'my-agent',
   *   agentName: 'MyAgent',
   * });
   * const tools = toolSet.getAllTools();
   *
   * const result = await generateText({
   *   model: yourModel,
   *   tools,
   *   maxSteps: 10,
   * });
   * ```
   */
  getAllTools(): Record<string, AIToolDefinition> {
    return {
      handoffrail_create_packet: this.createPacket(),
      handoffrail_claim_packet: this.claimPacket(),
      handoffrail_update_packet: this.updatePacket(),
      handoffrail_complete_packet: this.completePacket(),
      handoffrail_list_packets: this.listPackets(),
      handoffrail_get_packet: this.getPacket(),
      handoffrail_respond_to_hitl: this.respondToHitl(),
      handoffrail_get_packet_history: this.getPacketHistory(),
      handoffrail_chain_packet: this.chainPacket(),
    };
  }
}

// ── Convenience Factory ──────────────────────────────────────────────────

/**
 * Create a record of HandoffRail tool definitions for the Vercel AI SDK.
 *
 * This is a convenience wrapper around {@link HandoffRailToolSet.getAllTools}.
 *
 * @param client - An initialized {@link HandoffRailClient}.
 * @param options - Agent identity options.
 * @returns A record of AI SDK-compatible tool definitions.
 *
 * @example
 * ```typescript
 * import { generateText } from 'ai';
 * import { HandoffRailClient } from 'handoffrail-sdk';
 * import { createHandoffRailTools } from 'handoffrail-sdk/integrations/ai-sdk';
 *
 * const client = new HandoffRailClient({ baseUrl, apiKey });
 * const tools = createHandoffRailTools(client, {
 *   agentId: 'sales-01',
 *   agentName: 'SalesBot',
 * });
 *
 * const result = await generateText({
 *   model: openai('gpt-4o'),
 *   tools,
 *   maxSteps: 10,
 *   prompt: 'Check for any handoffs addressed to me',
 * });
 * ```
 */
export function createHandoffRailTools(
  client: HandoffRailClient,
  options: { agentId: string; agentName: string; framework?: string },
): Record<string, AIToolDefinition> {
  const toolSet = new HandoffRailToolSet(client, options);
  return toolSet.getAllTools();
}
