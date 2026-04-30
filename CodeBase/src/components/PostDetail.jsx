import { useState, useEffect } from "react";
import { getPost, deletePost } from "../db";

export default function PostDetail({ id, onBack, onEdit, onDeleted }) {
  const [post, setPost] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    getPost(id)
      .then(setPost)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  const handleDelete = async () => {
    if (!confirm("Delete this post?")) return;
    await deletePost(id);
    onDeleted();
  };

  if (loading) return <p className="status">Loading...</p>;
  if (error) return <p className="status error">{error}</p>;

  return (
    <div className="post-detail">
      <div className="detail-nav">
        <button className="btn-ghost" onClick={onBack}>← Back</button>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn-ghost" onClick={() => onEdit(id)}>Edit</button>
          <button className="btn-ghost danger" onClick={handleDelete}>Delete</button>
        </div>
      </div>
      <h1 className="detail-title">{post.title}</h1>
      <div className="post-meta" style={{ marginBottom: "2rem" }}>
        <span>{post.author}</span>
        <span>{new Date(post.createdAt).toLocaleDateString()}</span>
      </div>
      <p className="detail-content">{post.content}</p>
    </div>
  );
}