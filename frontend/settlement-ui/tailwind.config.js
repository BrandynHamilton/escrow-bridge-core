module.exports = {
    content: [
        './src/**/*.{js,ts,jsx,tsx}', // adjust based on project
    ],
    darkMode: 'class', // enables toggling with `.dark` class
    theme: {
        extend: {
            colors: {
                background: 'var(--color-background)',
                foreground: 'var(--color-foreground)',
                primary: 'var(--color-primary)',
                'primary-foreground': 'var(--color-primary-foreground)',
                // ... add others if you want to reference directly in `className`
            },
            borderRadius: {
                sm: 'var(--radius-sm)',
                md: 'var(--radius-md)',
                lg: 'var(--radius-lg)',
                xl: 'var(--radius-xl)',
            },
        },
    },
    plugins: [
        require('tw-animate-css'), // if you're using `tw-animate-css`
    ],
};
