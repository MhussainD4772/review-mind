
FROM node:20-slim

# Set working directory inside the container
WORKDIR /app

# Copy package files first (for Docker layer caching)
COPY web/package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the frontend code
COPY web/ .

#Expose Vite dev server port
EXPOSE 5173

#Run Vite dev server, bind to 0.0.0.0 it's rechable from outside the container
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


