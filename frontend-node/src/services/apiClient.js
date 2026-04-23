const axios = require("axios");

const apiClient = axios.create({
  baseURL: process.env.BACKEND_API_BASE || "http://localhost:8000",
  timeout: 120000
});

module.exports = { apiClient };
