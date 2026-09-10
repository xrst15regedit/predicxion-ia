web: gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --worker-class gthread --worker-tmp-dir /dev/shm --timeout 120 --access-logfile - --error-logfile -
