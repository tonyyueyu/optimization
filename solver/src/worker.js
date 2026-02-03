export default {
    async fetch(request, env) {
        let response = await env.ASSETS.fetch(request);

        if (response.status === 404) {
            response = await env.ASSETS.fetch(new URL('/index.html', request.url));
        }

        return response;
    }
};
