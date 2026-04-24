const axios = require("axios");

let baseUrl = process.env.BACKEND_API_BASE || "http://localhost:8000";
if (!baseUrl.startsWith("http")) {
  baseUrl = `http://${baseUrl}`;
}

const apiClient = axios.create({
  baseURL: baseUrl,
  timeout: 120000
});

module.exports = { apiClient };
