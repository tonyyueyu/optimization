# ---- Build Stage ----
# Use an official Node runtime as a parent image
FROM node:20-alpine AS build

# Set the working directory
WORKDIR /app

# Copy package.json and package-lock.json first for dependency caching
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application source code
COPY . .

# Build the React application for production
RUN npm run build

# ---- Final Stage ----
# Use a lightweight Nginx image
FROM nginx:stable-alpine

# Copy the built static files from the build stage to the Nginx html directory
COPY --from=build /app/dist /usr/share/nginx/html

# Copy the custom Nginx configuration file
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80
EXPOSE 80

# Default command to start Nginx
CMD ["nginx", "-g", "daemon off;"]
