import { Link } from 'react-router-dom';

export default function Brand() {
  return (
    <Link to="/" className="brand" aria-label="Luna home">
      <span className="mark" />
      <span className="word">Luna</span>
    </Link>
  );
}
