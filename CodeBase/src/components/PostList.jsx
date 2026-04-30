import { useState, useEffect } from "react";
import { getPosts, deletePost } from "../db";

export default function PostList({ onSelect, onEdit }) {
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    getPosts()
      .then(setPosts)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleDelete = async (e, id) => {
    e.stopPropagation();
    if (!confirm("Delete this post?")) return;
    await deletePost(id);
    setPosts((prev) => prev.filter((p) => p.id !== id));
  };

  if (loading) return <p className="status">Loading posts...</p>;
  if (error) return <p className="status error">{error}</p>;
  if (posts.length === 0) return <p className="status">No posts yet. Create one!</p>;

  return (
    <div className="post-list">
      <h1 className="page-title">All Posts</h1>
      {posts.map((post) => (
        <article key={post.id} className="post-card" onClick={() => onSelect(post.id)}>
          <div className="post-card-body">
            <h2 className="post-card-title">{post.title}</h2>
            <p className="post-card-excerpt">
              {post.content.length > 120 ? post.content.slice(0, 120) + "…" : post.content}
            </p>
            <div className="post-meta">
              <span>{post.author}</span>
              <span>{new Date(post.createdAt).toLocaleDateString()}</span>
            </div>
          </div>
          <div className="post-card-actions">
            <button className="btn-ghost" onClick={(e) => { e.stopPropagation(); onEdit(post.id); }}>Edit</button>
            <button className="btn-ghost danger" onClick={(e) => handleDelete(e, post.id)}>Delete</button>
          </div>
        </article>
      ))}
    </div>
  );
}