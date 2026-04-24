export interface AuthUser {
  user_id: string;
  username: string;
}

export interface TopicMeta {
  name: string;
  description: string;
  accent: string;
}

export type TopicMap = Record<string, TopicMeta>;
export type ModeMap = Record<string, string>;

export interface StatusResponse {
  database: string;
  database_url: string;
  providers: Record<string, boolean>;
  default_provider: string;
  frontend_built: boolean;
}

export interface QuestionItem {
  id: string;
  topic: string;
  mode: string;
  question: string;
  sequence: number;
  difficulty: string;
  solution: string;
  position: number;
  pool_size: number;
  options?: string[];
  answer?: string;
  constraints?: string;
  sample_input?: string;
  sample_output?: string;
  expected_approach?: string;
}

export interface SubmitResult {
  is_correct: boolean;
  feedback: string;
  solution: string;
  correct_answer: string;
  expected_approach: string;
}

export interface ChatEntry {
  id?: string;
  client_id?: string;
  user_id?: string;
  user_message: string;
  assistant_message: string;
  related_suggestions: string[];
  created_at: string;
  provider?: string;
}

export interface ChatPayload {
  user_id: string;
  message: string;
  topic?: string | null;
  mode?: string | null;
  provider?: string | null;
}

export interface ChatResponse {
  answer: string;
  related_suggestions: string[];
  provider: string;
}

export interface ChatStreamTokenEvent {
  type: "token";
  value: string;
}

export interface ChatStreamDoneEvent {
  type: "done";
  answer: string;
  related_suggestions: string[];
  provider: string;
}

export interface ChatStreamErrorEvent {
  type: "error";
  message: string;
}

export type ChatStreamEvent = ChatStreamTokenEvent | ChatStreamDoneEvent | ChatStreamErrorEvent;
