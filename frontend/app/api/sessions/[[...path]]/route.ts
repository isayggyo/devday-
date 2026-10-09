type Context = { params: Promise<{ path?: string[] }> };

async function proxy(request: Request, context: Context) {
  const { path = [] } = await context.params;
  if (path.some(part => !/^[a-zA-Z0-9_-]+$/.test(part))) return Response.json({ detail: { code: 'INVALID_PATH', message: 'Invalid request path' } }, { status: 400 });
  const base = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_BACKEND_URL ?? 'http://127.0.0.1:8000';
  const headers = new Headers();
  for (const key of ['Content-Type', 'Authorization', 'X-Dev-User-Id', 'X-E2E-Run-Id']) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  try {
    const upstream = await fetch(base + '/sessions' + (path.length ? '/' + path.join('/') : ''), {
      method: request.method, headers, cache: 'no-store',
      body: ['GET', 'HEAD'].includes(request.method) ? undefined : await request.arrayBuffer(),
      signal: AbortSignal.timeout(15000),
    });
    return new Response(upstream.body, { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('Content-Type') ?? 'application/json' } });
  } catch {
    return Response.json({ detail: { code: 'BACKEND_UNAVAILABLE', message: '서버 연결에 실패했습니다. 다시 시도해 주세요.' } }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
