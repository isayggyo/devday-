export type BackendHealth = {
  status: 'ok'; service: 'lecture-backend'; database: 'ok';
  auth_mode: 'development' | 'jwt'; e2e_enabled: boolean;
};

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) { super(message); this.status = status; this.code = code; }
}

export async function readJson<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (!response.ok) throw new ApiError(response.status, data.detail?.code ?? 'REQUEST_FAILED', data.detail?.message ?? '요청을 처리하지 못했습니다.');
  return data as T;
}
