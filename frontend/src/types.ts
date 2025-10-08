export type Msg = { type: 'system'|'human'|'ai'|'tool'; content: any };

export type SessionMeta = {
  session_id: string;
  session_name: string;
  created_at: number;
};

export type SessionsResp = {
  username?: string;
  sessions: SessionMeta[];
};