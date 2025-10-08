import type { Msg, SessionsResp } from './types';

const BASE = '/api';

export async function createUser(name: string, description: string) {
  const r = await fetch(`${BASE}/create_user`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name, description })
  });
  if (!r.ok) throw new Error('create_user failed');
  return r.json() as Promise<{ user_id: string; identity_token: string }>;
}

export async function createSession(token: string, session_name: string) {
  const r = await fetch(`${BASE}/create_session`, {
    method: 'POST',
    headers: {'Content-Type':'application/json', 'X-Identity-Token': token},
    body: JSON.stringify({ session_name })
  });
  if (!r.ok) throw new Error('create_session failed');
  return r.json() as Promise<{ session_id: string }>;
}

export async function getSessions(token: string) {
  const r = await fetch(`/api/get_sessions`, {
    headers: {'X-Identity-Token': token}
  });
  if (!r.ok) throw new Error('get_sessions failed');
  return r.json() as Promise<SessionsResp>;
}

export async function getConversationHistory(token: string, session_id: string) {
  const r = await fetch(`${BASE}/get_conversation_history?session_id=${encodeURIComponent(session_id)}`, {
    headers: {'X-Identity-Token': token}
  });
  if (!r.ok) throw new Error('get_conversation_history failed');
  return r.json() as Promise<{ messages: Msg[] }>;
}

export async function chatOnce(token: string, session_id: string, text: string) {
  const r = await fetch(`${BASE}/chat?stream=0`, {
    method: 'POST',
    headers: {'Content-Type':'application/json', 'X-Identity-Token': token},
    body: JSON.stringify({
      session_id,
      message: { type: 'human', content: text }
    })
  });
  if (!r.ok) throw new Error('chat failed');
  return r.json() as Promise<{ last_ai: Msg }>;
}
