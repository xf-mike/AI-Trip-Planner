export type Msg = { type: 'system'|'human'|'ai'|'tool'; content: any };

export type SessionMeta = {
  session_id: string;
  session_name: string;
  created_at: number;
};

export type SessionsResp = {
  user_id: string;
  username?: string;
  sessions: SessionMeta[];
};

// 基础用户信息对象 (ID + Name)
export interface UserSimple {
  id: string;
  name: string;
}

// 关系接口响应结构
export interface RelationshipsResp {
  exposed_to: UserSimple[];   // 我授权给谁看 (我 -> 他)
  amplify_from: UserSimple[]; // 我在看谁 (他 -> 我)
}