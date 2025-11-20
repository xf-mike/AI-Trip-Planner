import type { Msg, SessionsResp, RelationshipsResp } from './types';

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
  const r = await fetch(`${BASE}/get_sessions`, {
    headers: {'X-Identity-Token': token}
  });
  if (!r.ok) throw new Error('get_sessions failed');
  return r.json() as Promise<SessionsResp>;
}

// 获取当前用户的关系网 (返回 {id, name} 列表)
export async function getRelationships(token: string) {
  const r = await fetch(`${BASE}/get_relationships`, {
    headers: {'X-Identity-Token': token}
  });
  if (!r.ok) throw new Error('get_relationships failed');
  return r.json() as Promise<RelationshipsResp>;
}

// 更新关系网
// payload: 使用 string[] 发送 ID 列表
// response: 返回更新后的 RelationshipsResp (包含 {id, name} 对象)
export async function updateRelationships(
  token: string, 
  payload: { exposed_to?: string[], amplify_from?: string[] }
) {
  const r = await fetch(`${BASE}/update_relationships`, {
    method: 'POST',
    headers: {'Content-Type':'application/json', 'X-Identity-Token': token},
    body: JSON.stringify(payload)
  });
  if (!r.ok) throw new Error('update_relationships failed');
  return r.json() as Promise<{ status: string; current: RelationshipsResp }>;
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
