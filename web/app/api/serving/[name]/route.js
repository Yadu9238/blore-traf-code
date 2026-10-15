import path from 'node:path';
import { readFile } from 'node:fs/promises';

// Fixed allow-list: the file name comes from the URL, so it must never reach the filesystem unchecked.
const FILES = new Set(['corridors.json', 'baselines.json', 'latest.json', 'insights.json', 'health.json']);

const SERVING_DIR =
  process.env.TRAFFIC_SERVING_DIR || path.join(/*turbopackIgnore: true*/ process.cwd(), '..', 'data', 'serving');

export const dynamic = 'force-dynamic';

export async function GET(_request, { params }) {
  const { name } = await params;
  if (!FILES.has(name)) {
    return Response.json({ error: 'Unknown serving file' }, { status: 404 });
  }

  try {
    const body = await readFile(path.join(/*turbopackIgnore: true*/ SERVING_DIR, name), 'utf-8');
    return new Response(body, {
      headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
    });
  } catch (err) {
    if (err.code === 'ENOENT') {
      return Response.json(
        { error: `${name} has not been produced yet. Run the transform workflow, then git pull.` },
        { status: 404 },
      );
    }
    return Response.json({ error: 'Could not read serving data' }, { status: 500 });
  }
}
