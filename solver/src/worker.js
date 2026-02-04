export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname.startsWith('/api/')) {
      return fetch(request);
    }

    let response = await env.ASSETS.fetch(request);

    if (response.status === 404) {
      response = await env.ASSETS.fetch(new URL('/index.html', request.url));
    }

    return response;
  }
};
