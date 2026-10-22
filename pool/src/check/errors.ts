/** Network/protocol level failures while talking to a proxy or target. */
export class NET_CHECK extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = 'NET_CHECK';
  }
}

/** A fetch target used to validate a proxy end to end. */
export interface EchoTarget {
  url: string;
  /** how to interpret the response */
  parser: 'text' | 'json' | 'none';
  label: string;
}

export interface EchoResponse {
  target: string;
  ok: boolean;
  statusCode: number | null;
  /** IP the target saw as the peer (exit address) */
  remoteIp: string | null;
  headers: Record<string, string>;
  roundTripMs: number;
  error?: string;
}
