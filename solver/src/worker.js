export default {
    async fetch(request, env) {
        const url = new URL(request.url);

        // Attempt to serve the static asset from valid paths
        let response = await env.ASSETS.fetch(request);

        // For Single Page Applications (SPA), if the asset is not found (404)
        // and it's not a file request (doesn't have an extension), 
        // fallback to index.html
        if (response.status === 404 && !url.pathname.includes('.')) {
            response = await env.ASSETS.fetch(new URL('/index.html', request.url));
        }

        return response;
    }
};
