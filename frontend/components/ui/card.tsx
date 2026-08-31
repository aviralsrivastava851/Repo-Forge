export function Card({ className="", ...props }: any) { return <div className={`border rounded-lg bg-white ${className}`} {...props} />; }
export function CardHeader({ className="", ...props }: any) { return <div className={`p-4 border-b ${className}`} {...props} />; }
export function CardContent({ className="", ...props }: any) { return <div className={`p-4 ${className}`} {...props} />; }
export function Badge({ className="", ...props }: any) { return <span className={`px-2 py-0.5 rounded text-xs bg-secondary ${className}`} {...props} />; }
