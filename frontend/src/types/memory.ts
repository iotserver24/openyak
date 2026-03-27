export type MemoryCategory = "preference" | "knowledge" | "context" | "behavior" | "goal";
export type ContextSection = "work_context" | "personal_context" | "top_of_mind";

export interface MemoryFact {
  id: string;
  content: string;
  category: MemoryCategory;
  confidence: number;
  source_session_id: string | null;
  time_created: string | null;
}

export interface MemoryResponse {
  contexts: Record<string, string>;
  facts: MemoryFact[];
}

export interface AddFactRequest {
  content: string;
  category?: MemoryCategory;
  confidence?: number;
}

export interface UpdateContextRequest {
  section: ContextSection;
  summary: string;
}

export interface RemoveFactsRequest {
  fact_ids: string[];
}
