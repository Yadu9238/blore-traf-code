import { Geist, Geist_Mono } from 'next/font/google';
import './globals.css';
import './traffic.css';

const geist = Geist({ subsets: ['latin'], display: 'swap', variable: '--font-sans' });
const geistMono = Geist_Mono({ subsets: ['latin'], display: 'swap', variable: '--font-mono' });

export const metadata = {
  title: 'Bangalore tech corridor traffic',
  description: 'Travel time on Bangalore tech corridors compared with what is normal for the hour, and the best time to leave.',
  robots: { index: false, follow: false },
};

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  themeColor: '#0b0b0b',
};

// Runs before paint so a saved light preference never flashes dark first.
const themeBootstrap = `(function(){try{if(localStorage.getItem('theme')==='light'){document.documentElement.classList.remove('dark')}}catch(e){}})();`;

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`dark ${geist.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
