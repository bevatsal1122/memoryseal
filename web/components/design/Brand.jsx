export function BrandMark({ className = "brand-mark" }) {
  return (
    <img
      className={className}
      src="/icon.svg"
      width="64"
      height="64"
      alt=""
      aria-hidden="true"
      draggable="false"
    />
  );
}

export default function Brand() {
  return (
    <span className="brand">
      <BrandMark />
      <span>
        memoryseal<span className="brand-dot">.</span>
      </span>
    </span>
  );
}
