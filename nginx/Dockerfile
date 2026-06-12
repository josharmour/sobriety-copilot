FROM nginx:1.27-alpine

RUN rm -rf /usr/share/nginx/html/*

COPY static/ /usr/share/nginx/html/
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
