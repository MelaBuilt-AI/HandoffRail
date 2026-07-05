/**
 * Test helper — in-memory HTTP server for testing the sync client.
 */

import * as http from 'http';
import { AddressInfo } from 'net';

export interface MockRoute {
  method: string;
  /** Path to match. For parameterized routes like /api/v1/packets/{id},
   *  provides an exact match. Set `parameterized: true` for prefix matching. */
  path: string;
  status: number;
  body: unknown;
  validate?: (body: unknown) => void;
  /** If true, match any path starting with this route path (for parameterized routes). */
  parameterized?: boolean;
}

export class TestServer {
  private server: http.Server;
  private routes: MockRoute[] = [];
  public url: string = '';

  constructor() {
    this.server = http.createServer((req, res) => {
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('Access-Control-Allow-Methods', '*');
      res.setHeader('Access-Control-Allow-Headers', '*');

      if (req.method === 'OPTIONS') {
        res.writeHead(204);
        res.end();
        return;
      }

      const requestPath = (req.url ?? '').split('?')[0];

      const chunks: Buffer[] = [];
      req.on('data', (chunk: Buffer) => chunks.push(chunk));
      req.on('end', () => {
        const body =
          chunks.length > 0 ? JSON.parse(Buffer.concat(chunks).toString()) : null;

        // Find matching route — exact match first, then parameterized
        const route = this.routes.find((r) => {
          if (r.method !== req.method) return false;
          if (r.parameterized) {
            return requestPath.startsWith(r.path);
          }
          return r.path === requestPath;
        });

        if (route) {
          if (route.validate && body) {
            try {
              route.validate(body);
            } catch (e) {
              res.writeHead(400, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ detail: (e as Error).message }));
              return;
            }
          }
          res.writeHead(route.status, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify(route.body));
        } else {
          res.writeHead(404, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ detail: `Route not found: ${req.method} ${requestPath}` }));
        }
      });
    });
  }

  addRoute(route: MockRoute): void {
    this.routes.push(route);
  }

  clearRoutes(): void {
    this.routes = [];
  }

  async start(): Promise<void> {
    return new Promise((resolve) => {
      this.server.listen(0, '127.0.0.1', () => {
        const addr = this.server.address() as AddressInfo;
        this.url = `http://127.0.0.1:${addr.port}/api/v1`;
        resolve();
      });
    });
  }

  async stop(): Promise<void> {
    return new Promise((resolve) => {
      this.server.close(() => resolve());
    });
  }
}
