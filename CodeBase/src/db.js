// db.js — simulated backend using an in-memory array
// Replace these functions with real API calls when ready

let posts = [
  {
    id: 1,
    title: "Getting Started with React",
    content: "React is a JavaScript library for building user interfaces. It lets you compose complex UIs from small, isolated pieces of code called components.",
    author: "Abdallah",
    createdAt: new Date("2026-04-01").toISOString(),
  },
  {
    id: 2,
    title: "Why In-Memory State is Great for Prototyping",
    content: "When building a dummy codebase or proof of concept, an in-memory array is often the fastest path to a working app. No DB setup, no migrations — just pure logic.",
    author: "Abdallah",
    createdAt: new Date("2026-04-15").toISOString(),
  },
];

let nextId = 3;

// Simulate async delay like a real API
const delay = (ms = 200) => new Promise((res) => setTimeout(res, ms));

export async function getPosts() {
  await delay();
  return [...posts].sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
}

export async function getPost(id) {
  await delay();
  const post = posts.find((p) => p.id === id);
  if (!post) throw new Error(`Post ${id} not found`);
  return { ...post };
}

export async function createPost({ title, content, author }) {
  await delay();
  const post = {
    id: nextId++,
    title,
    content,
    author,
    createdAt: new Date().toISOString(),
  };
  posts.push(post);
  return { ...post };
}

export async function updatePost(id, { title, content, author }) {
  await delay();
  const index = posts.findIndex((p) => p.id === id);
  if (index === -1) throw new Error(`Post ${id} not found`);
  posts[index] = { ...posts[index], title, content, author };
  return { ...posts[index] };
}

export async function deletePost(id) {
  await delay();
  const index = posts.findIndex((p) => p.id === id);
  if (index === -1) throw new Error(`Post ${id} not found`);
  posts.splice(index, 1);
  return { success: true };
}