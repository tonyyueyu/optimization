export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const BACKEND_URL = "https://backend-service-696616516071.us-west1.run.app";

    if (url.pathname.startsWith('/api/')) {
      const newUrl = new URL(url.pathname + url.search, BACKEND_URL);
      
      const newRequest = new Request(newUrl, request);
      
      return fetch(newRequest);
    }

    let response = await env.ASSETS.fetch(request);
    if (response.status === 404) {
      return env.ASSETS.fetch(new URL('/index.html', request.url));
    }

    return response;
  }
};