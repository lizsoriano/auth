# Reflexión: ¿por qué usar Redis en los microservicios?

Yo pienso que usar Redis en los microservicios ayuda a que la aplicación responda más rápido, porque evita buscar lo mismo en la base de datos cada vez. Por ejemplo, si muchas personas consultan el catálogo, los autores o los libros más pedidos, conviene guardar esos resultados temporalmente en Redis. Así se reduce el trabajo de PostgreSQL. También se podrían guardar favoritos, pero separados por usuario para que nadie vea información que no le corresponde.

No guardaría toda la información en Redis. Los datos personales, pedidos y pagos deben mantenerse en PostgreSQL como información definitiva y estar protegidos con permisos. Redis serviría como apoyo para las búsquedas frecuentes, las sesiones y el control de los tokens. Además, cuando cambie un dato, se debe actualizar o borrar su copia en caché para no mostrar información vieja.

En mi aplicación, los endpoints de consulta de libros y autores son adecuados para usar caché. En cambio, los de usuarios, pedidos y pagos necesitan JWT para comprobar quién está haciendo la petición y qué tiene permitido hacer. Tener un token válido no significa que puedas consultar los pedidos de otra persona o modificar cualquier usuario.

Login genera el JWT y los demás microservicios lo validan con la configuración compartida. También consultan Redis para revisar si el token fue revocado. Así, cuando cierro sesión, los demás servicios pueden detectar que ese token ya no debe aceptarse. En pagos, Redis también ayuda a controlar los reintentos para que una misma operación no se cobre dos veces.

Para implementarlo, usaría tiempos de vencimiento en la caché, claves separadas por recurso y usuario cuando sea necesario, y borraría las entradas afectadas después de modificar información. Si Redis falla, una consulta pública del catálogo puede seguir usando PostgreSQL. Pero si no se puede verificar un token o coordinar un pago, es mejor devolver un error temporal. Para mí, Redis aporta rapidez y coordinación, mientras que JWT y los permisos ayudan a controlar el acceso a cada microservicio.
