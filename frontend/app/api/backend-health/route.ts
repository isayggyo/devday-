export async function GET() {
  const base = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://127.0.0.1:8000';
  try {
    const response = await fetch(base + '/health', { cache: 'no-store', signal: AbortSignal.timeout(5000) });
    return Response.json(await response.json(), { status: response.status });
  } catch {
    return Response.json({ detail: { code: 'BACKEND_UNAVAILABLE', message: '백엔드에 연결할 수 없습니다.' } }, { status: 503 });
  }
}
