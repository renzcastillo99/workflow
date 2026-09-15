import FadeIn from './FadeIn';

const LINKS = ['About', 'Price', 'Projects', 'Contact'];

export default function Navbar() {
  return (
    <FadeIn delay={0} y={-20} className="w-full">
      <nav className="flex justify-between px-6 md:px-10 pt-6 md:pt-8">
        {LINKS.map((link) => (
          <a
            key={link}
            href={`#${link.toLowerCase()}`}
            className="text-[#D7E2EA] font-medium uppercase tracking-wider text-sm md:text-lg lg:text-[1.4rem] hover:opacity-70 transition-opacity duration-200"
          >
            {link}
          </a>
        ))}
      </nav>
    </FadeIn>
  );
}
